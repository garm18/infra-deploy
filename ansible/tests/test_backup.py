import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_guard import guard

namespace = {k: v for k, v in vars(guard).items() if not k.startswith('__')}
namespace['__name__'] = 'backup_tests'
source = Path(__file__).parents[1] / 'files/backup.py'
exec(compile(source.read_text(), str(source), 'exec'), namespace)


class BackupTests(unittest.TestCase):
    def test_reject_link_and_traversal_archives(self):
        for name, kind in [('data/link', tarfile.SYMTYPE), ('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE)]:
            with tempfile.TemporaryDirectory() as root:
                archive = Path(root) / 'bad.tar'
                with tarfile.open(archive, 'w') as out:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = '/etc/passwd'
                    out.addfile(member)
                with self.assertRaises(ValueError):
                    namespace['extract_safe'](archive, Path(root) / 'out')
                self.assertFalse((Path(root) / 'out').exists())

    def test_hash_does_not_read_entire_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'dump'
            path.write_bytes(b'content' * 200000)
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded read')):
                self.assertEqual(namespace['file_sha256'](path), hashlib.sha256(b'content' * 200000).hexdigest())

    def test_manifest_requires_all_exact_files(self):
        for files in ({}, {'../database.dump': 'x'}, {'database.dump': 'bad'}):
            with tempfile.TemporaryDirectory() as root:
                with self.assertRaises(ValueError):
                    namespace['verify_manifest_files']({'kind': 'postgres', 'files': files}, Path(root))

    def test_backup_request_rejects_non_data_and_missing_service(self):
        payload = {'backup': {'id': 'b1', 'service': 'db'}, 'services': [{'id':'db', 'kind':'postgres'}],
                   'bundle': {'compose': {'services': {'db': {}}}}}
        self.assertEqual(namespace['backup_service'](payload)['kind'], 'postgres')
        payload['services'][0]['kind'] = 'nginx'
        with self.assertRaises(ValueError):
            namespace['backup_service'](payload)
        payload['services'] = []
        with self.assertRaises(ValueError):
            namespace['backup_service'](payload)

    def test_postgres_snapshot_requires_review_for_extra_roles(self):
        old = namespace['command_in_service']
        from types import SimpleNamespace
        namespace['command_in_service'] = lambda *args, **kwargs: SimpleNamespace(stdout=b'postgres\napp\nextra\n')
        try:
            with tempfile.TemporaryDirectory() as root:
                with self.assertRaises(ValueError):
                    namespace['snapshot_database']({}, {'kind':'postgres','config':{'username':'app'}}, Path(root))
                self.assertEqual(list(Path(root).iterdir()), [])
        finally:
            namespace['command_in_service'] = old

    def test_restore_refuses_active_target_before_decryption(self):
        old = namespace['context']
        with tempfile.TemporaryDirectory() as root:
            namespace['context'] = lambda p: (Path(root), Path(root) / 'data')
            try:
                payload = {'backup': {'id':'b1','service':'db'}, 'services':[{'id':'db','kind':'postgres'}],
                           'bundle':{'compose':{'services':{'db':{}}}}}
                with self.assertRaises(ValueError):
                    namespace['restore_run'](payload)
            finally:
                namespace['context'] = old

    def test_restore_database_uses_stream_and_new_target_credentials(self):
        old_command, old_compose = namespace['command_in_service'], namespace['compose']
        calls = []
        namespace['compose'] = lambda *args, **kwargs: None
        namespace['command_in_service'] = lambda *args, **kwargs: calls.append((args,kwargs))
        try:
            with tempfile.TemporaryDirectory() as root:
                path = Path(root)
                (path / 'database.dump').write_bytes(b'dump')
                with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded read')):
                    namespace['restore_database']({}, {'id':'db','kind':'postgres','config':{'username':'app','database':'app'}}, path)
            self.assertIn('input_file', calls[0][1])
            self.assertIn('--no-owner', calls[0][0][2])
        finally:
            namespace['command_in_service'], namespace['compose'] = old_command, old_compose

    def test_backup_atomically_publishes_encrypted_archive(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, destination = Path(root) / 'runtime', Path(root) / 'external'
            runtime.mkdir()
            destination.mkdir()
            payload = {'backup': {'id':'b1','service':'db','destination':str(destination),'recipient':'age1'+'a'*32},
                       'services':[{'id':'db','kind':'postgres','image':'postgres:pinned','config':{'username':'app','database':'app'}}],
                       'bundle':{'compose':{'services':{'db':{}}}}}
            def snapshot(payload, service, staging):
                (staging / 'database.dump').write_bytes(b'data')
                (staging / 'roles.json').write_text('["postgres","app"]')
            def age(argv, **kwargs):
                kwargs['stdout'].write(b'encrypted-ciphertext')
            with patch.dict(namespace, external_directory=lambda value: destination, context=lambda value:(runtime,Path(root)/'data'), snapshot_database=snapshot, run=age), patch.object(guard.shutil,'which',return_value='/usr/bin/age'):
                result = namespace['backup_run'](payload)
                self.assertEqual(Path(result['archive']).read_bytes(), b'encrypted-ciphertext')
                self.assertEqual(result['sha256'],hashlib.sha256(b'encrypted-ciphertext').hexdigest())
                self.assertFalse((destination / '.b1.partial').exists())
                with self.assertRaises(ValueError):
                    namespace['backup_run'](payload)

    def test_storage_snapshot_restarts_only_previously_running_after_failure(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            (data / 'store/data').mkdir(parents=True)
            (data / 'store/data/link').symlink_to('/etc/passwd')
            commands=[]
            service={'id':'store','kind':'minio','host':'one'}
            with patch.dict(namespace, context=lambda value:(Path(root),data), running_services=lambda value:['store'], compose=lambda payload,args,**kwargs:commands.append(args)):
                with self.assertRaises(ValueError):
                    namespace['snapshot_storage']({'services':[service]},service,Path(root))
            self.assertEqual(commands[0][0], 'stop')
            self.assertEqual(commands[-1][0], 'up')
            self.assertEqual(commands[-1][-1], 'store')
