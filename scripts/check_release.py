#!/usr/bin/env python3
"""Validate operator evidence; scan candidates without manufacturing approval."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess

IMAGE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}$')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate evidence field')
        result[key] = value
    return result


def validate_evidence(path, images, required_checks=()):
    """Return validation errors. Evidence is a trusted operator input, not a signature."""
    try:
        evidence = json.loads(Path(path).read_text(), object_pairs_hook=unique_object)
    except (OSError, ValueError, UnicodeError):
        return ['Evidence unavailable or invalid JSON']
    if not isinstance(evidence, dict):
        return ['Evidence must be an object']
    errors = []
    approved = evidence.get('approved_images')
    if not isinstance(approved, list) or not approved or any(
            not isinstance(item, str) or not IMAGE.fullmatch(item) for item in approved):
        errors.append('approved_images must contain digest-pinned image references')
    else:
        if any(item not in approved for item in images):
            errors.append('Requested image is not approved')
    approver = evidence.get('approved_by')
    if not isinstance(approver, str) or not approver.strip():
        errors.append('approved_by is required')
    try:
        expiry = datetime.fromisoformat(evidence.get('expires_at', '').replace('Z', '+00:00'))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            errors.append('Evidence expired or timestamp lacks timezone')
    except (ValueError, TypeError, AttributeError):
        errors.append('expires_at must be an ISO8601 timestamp')
    checks = evidence.get('checks')
    if not isinstance(checks, dict) or any(not isinstance(value, bool) for value in checks.values()):
        errors.append('checks must map names to booleans')
    elif any(checks.get(check) is not True for check in required_checks):
        errors.append('Required verification checks are missing or failed')
    return errors


def scan_image(image, output_directory):
    if not IMAGE.fullmatch(image):
        raise ValueError('Scan requires a digest-pinned image')
    scanner = shutil.which('trivy')
    if scanner is None:
        raise RuntimeError('Trivy unavailable; no scan or SBOM evidence generated')
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    commands = [
        [scanner, 'image', '--format', 'json', '--output', str(output / 'scan.json'),
         '--severity', 'HIGH,CRITICAL', '--exit-code', '1', image],
        [scanner, 'image', '--format', 'cyclonedx', '--output', str(output / 'sbom.json'), image],
    ]
    codes = []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        (output / ('scan.log' if len(codes) == 0 else 'sbom.log')).write_text(
            result.stdout + result.stderr)
        codes.append(result.returncode)
    return 1 if any(codes) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--evidence', type=Path)
    mode.add_argument('--scan')
    parser.add_argument('--image', action='append', default=[])
    parser.add_argument('--required-check', action='append', default=[])
    parser.add_argument('--output', default='.reports/image-scan')
    args = parser.parse_args(argv)
    if args.scan:
        try:
            return scan_image(args.scan, args.output)
        except (OSError, ValueError, RuntimeError) as error:
            print(str(error))
            return 2
    errors = validate_evidence(args.evidence, args.image, args.required_check)
    print(json.dumps({'valid': not errors, 'errors': errors}))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
