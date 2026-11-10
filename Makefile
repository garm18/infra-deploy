# One target performs one action. No implicit installation or deployment.
.DEFAULT_GOAL := help
SHELL := /bin/sh
.DELETE_ON_ERROR:
.SUFFIXES:
.NOTPARALLEL:
MAKEFLAGS += --no-builtin-rules
# References: makefile-generator/docs/patterns-guide.md and security-guide.md

DD_PYTHON ?= python3
export DD_PYTHON CONFIG PLAN ENVIRONMENT DEPLOYMENT HOST SERVICE CONFIRM
export STATE_DIR VAULT_PASSWORD_FILE

.PHONY: help doctor catalog wizard validate secrets-init plan apply preflight status logs stop test coverage

help:
	@printf '%s\n' \
	  'Dynamic Deployment — jalankan satu langkah setiap kali:' \
	  '  make infra-help                      Stack infrastructure existing' \
	  '  make infra-up ENV=local SERVICES=redis' \
	  '  make infra-ansible INVENTORY=/path/hosts INFRA_VARS=/path/vars.yml'  \
	  '  make doctor                          Periksa kebutuhan controller' \
	  '  make catalog                         Lihat layanan yang tersedia' \
	  '  make wizard CONFIG=configs/demo.yml  Buat konfigurasi interaktif' \
	  '  make validate CONFIG=configs/demo.yml' \
	  '  make secrets-init CONFIG=configs/demo.yml' \
	  '  make plan CONFIG=configs/demo.yml    Buat plan; simpan path hasilnya' \
	  '  make apply PLAN="/path/plan.json" ENVIRONMENT=staging DEPLOYMENT=demo' \
	  '  make preflight CONFIG=configs/demo.yml [HOST=app] [SERVICE=web]' \
	  '  make status CONFIG=configs/demo.yml [HOST=app] [SERVICE=web]' \
	  '  make logs CONFIG=configs/demo.yml [HOST=app] [SERVICE=web]' \
	  '  make stop CONFIG=configs/demo.yml HOST=app SERVICE=web CONFIRM=yes' \
	  '  make test                            Jalankan unit dan integration test lokal' \
	  '  make coverage                        Periksa coverage minimal 80%' \
	  'Opsional: DD_PYTHON=/path/python STATE_DIR="/path/state" VAULT_PASSWORD_FILE="/path/password"' \
	  'CONFIG dan path relatif dihitung dari direktori dynamic_deployment.' \
	  'SERVICE memilih satu layanan. Jalankan kembali untuk layanan lain.'

# Read exported values through the shell; never interpolate user values as code.
doctor catalog wizard validate secrets-init plan apply preflight status logs stop:
	@set -eu; \
	  require() { if [ -z "$$2" ]; then printf 'Isi %s terlebih dahulu. Lihat make help.\n' "$$1" >&2; exit 2; fi; }; \
	  set --; \
	  if [ -n "$${STATE_DIR:-}" ]; then set -- "$$@" --state-dir "$$STATE_DIR"; fi; \
	  set -- "$$@" "$@"; \
	  case "$@" in \
	    wizard|validate|plan|secrets-init|preflight|status|logs|stop) require CONFIG "$${CONFIG:-}" ;; \
	  esac; \
	  case "$@" in \
	    wizard) set -- "$$@" --output "$$CONFIG" ;; \
	    validate|plan) set -- "$$@" "$$CONFIG" ;; \
	    secrets-init|preflight|status|logs|stop) set -- "$$@" --config "$$CONFIG" ;; \
	    apply) \
	      require PLAN "$${PLAN:-}"; \
	      require ENVIRONMENT "$${ENVIRONMENT:-}"; \
	      require DEPLOYMENT "$${DEPLOYMENT:-}"; \
	      set -- "$$@" --plan "$$PLAN" --environment "$$ENVIRONMENT" --deployment "$$DEPLOYMENT" ;; \
	  esac; \
	  if [ "$@" = stop ]; then \
	    require HOST "$${HOST:-}"; require SERVICE "$${SERVICE:-}"; \
	    if [ "$${CONFIRM:-}" != yes ]; then printf '%s\n' 'Stop dibatalkan. Tambahkan CONFIRM=yes untuk menghentikan layanan.' >&2; exit 2; fi; \
	  fi; \
	  case "$@" in \
	    preflight|status|logs|stop) \
	      if [ -n "$${HOST:-}" ]; then set -- "$$@" --host "$$HOST"; fi; \
	      if [ -n "$${SERVICE:-}" ]; then set -- "$$@" --service "$$SERVICE"; fi ;; \
	  esac; \
	  if [ "$@" = stop ]; then set -- "$$@" --yes; fi; \
	  case "$@" in \
	    apply|secrets-init|preflight|status|logs|stop) \
	      if [ -n "$${VAULT_PASSWORD_FILE:-}" ]; then set -- "$$@" --vault-password-file "$$VAULT_PASSWORD_FILE"; fi ;; \
	  esac; \
	  exec bash ./setup.sh "$$@"

test:
	@PYTHONPATH="$$PWD/src$${PYTHONPATH:+:$$PYTHONPATH}" PYTHONDONTWRITEBYTECODE=1 \
	  "$$DD_PYTHON" -m unittest discover -s tests -v
	@PYTHONPATH="$$PWD/src$${PYTHONPATH:+:$$PYTHONPATH}" PYTHONDONTWRITEBYTECODE=1 \
	  "$$DD_PYTHON" -m unittest discover -s ansible/tests -v

coverage:
	@PYTHONPATH="$$PWD/src$${PYTHONPATH:+:$$PYTHONPATH}" PYTHONDONTWRITEBYTECODE=1 \
	  "$$DD_PYTHON" scripts/measure_coverage.py --minimum 80

.PHONY: infra-help infra-init infra-check infra-config infra-network infra-build infra-pull infra-up infra-deploy infra-ps infra-logs infra-stop infra-down infra-test infra-ansible
infra-help infra-init infra-check infra-config infra-network infra-build infra-pull infra-up infra-deploy infra-ps infra-logs infra-stop infra-down infra-test:
	@$(MAKE) --no-print-directory -C infrastructure $(patsubst infra-%,%,$@)

export INVENTORY INFRA_VARS
infra-ansible:
	@test -n "$${INVENTORY:-}" && test -n "$${INFRA_VARS:-}" || { printf '%s\n' 'Isi INVENTORY dan INFRA_VARS (lihat docs/integration.md)' >&2; exit 2; }
	@ANSIBLE_CONFIG="$$PWD/ansible/ansible.cfg" ansible-playbook -i "$$INVENTORY" ansible/infrastructure.yml -e "@$$INFRA_VARS"
