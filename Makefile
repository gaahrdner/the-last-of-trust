.PHONY: help build up down restart status logs ssh pcrs ima eventlog enroll attest history bmc-status bmc-firmware bmc-reset attack-injection attack-replay attack-quarantine test clean

BMC_AUTH ?= root:0penBmc

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

build: ## Build all container images
	docker compose build

up: ## Start host, BMC, and verifier containers
	docker compose up -d

down: ## Stop containers (preserves VM disk & TPM state)
	docker compose down

restart: ## Restart all containers
	docker compose restart

status: ## Show container health and status
	docker compose ps

logs: ## Follow logs from all containers
	docker compose logs -f

ssh: ## SSH into the measured-boot Debian host VM (password: lab)
	ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 lab@127.0.0.1

pcrs: ## Read live TPM 2.0 SHA-256 PCRs from the host
	curl -sf http://127.0.0.1:8081/tpm/pcrs | jq .

ima: ## Show summary of Linux IMA runtime measurements from the host
	curl -sf http://127.0.0.1:8081/ima/log | jq '{available, count, sample: .entries[-5:]}'

eventlog: ## Decode UEFI/GRUB TPM 2.0 binary event log via verifier
	curl -sf http://127.0.0.1:8888/api/v1/eventlog | jq .

enroll: ## Enroll host TPM 2.0 Attestation Key & golden PCR baseline in verifier
	curl -sf -X POST http://127.0.0.1:8888/api/v1/enroll | jq .

attest: ## Run cryptographic TPM 2.0 remote attestation against the host
	curl -s -X POST http://127.0.0.1:8888/api/v1/attest | jq .

history: ## Show recent attestation history from verifier
	curl -sf http://127.0.0.1:8888/api/v1/history | jq .

bmc-status: ## Query host state via BMC Redfish API
	curl -skf -u $(BMC_AUTH) https://127.0.0.1:8443/redfish/v1/Systems/host | jq .

bmc-firmware: ## Query active host firmware inventory via BMC Redfish API
	curl -skf -u $(BMC_AUTH) https://127.0.0.1:8443/redfish/v1/UpdateService/FirmwareInventory/host-firmware | jq .

bmc-reset: ## Hard-reset the host VM via BMC Redfish ComputerSystem.Reset
	curl -skf -u $(BMC_AUTH) -X POST \
		-H 'Content-Type: application/json' \
		-d '{"ResetType":"ForceRestart"}' \
		https://127.0.0.1:8443/redfish/v1/Systems/host/Actions/ComputerSystem.Reset | jq .

attack-injection: ## Run attack 01: untrusted runtime script injection (IMA + PCR 10)
	./scripts/attacks/01-runtime-injection.sh

attack-replay: ## Run attack 02: TPM 2.0 quote replay with stale nonce
	./scripts/attacks/02-quote-replay.sh

attack-quarantine: ## Run attack 03: tamper -> BMC ForceOff quarantine -> Redfish recovery
	./scripts/attacks/03-bmc-quarantine.sh

test: ## Run full end-to-end verification (measured boot, Redfish, attestation, tamper detection)
	./scripts/verify.sh

clean: ## Stop containers and delete persistent VM, TPM, and verifier volumes
	docker compose down -v
