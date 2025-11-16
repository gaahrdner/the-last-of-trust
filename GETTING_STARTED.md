# Getting Started with The Last of Trust

## What You Have Right Now

You have a **firmware security research environment** with:
- A host running QEMU (like a virtual computer inside Docker)
- A BMC (Baseboard Management Controller) for out-of-band management
- Software TPM for trusted computing experiments
- Network isolation for security testing

## Quick Start: Three Ways to Use This

### 🔍 Level 1: Explore the Containers (5 minutes)

**No Debian install needed!** Just explore the infrastructure:

```bash
# 1. Check what's running
docker compose ps

# 2. Enter the host container (where QEMU runs)
docker exec -it tlot-host /bin/bash

# Inside the container, check:
ps aux                          # See QEMU and TPM processes
ls -la /var/lib/host/          # See the Debian disk image
ls -la /firmware/              # Firmware directory
cat /logs/debian_setup.log     # Setup logs

# 3. Check the TPM
ls -la /var/lib/host/tpm/      # TPM state
ps aux | grep swtpm            # TPM process

# 4. Exit
exit
```

**Check the BMC:**
```bash
docker exec -it tlot-bmc /bin/bash

# Inside BMC:
ps aux                         # See what's running
ls -la /var/lib/openbmc/       # BMC data
exit
```

**View what QEMU is doing:**
```bash
# Attach to QEMU console (you'll see BIOS output)
docker attach tlot-host

# To detach: Press Ctrl-P then Ctrl-Q
# (Or Ctrl-C to stop the container)
```

---

### 🐧 Level 2: Install Debian in QEMU (30 minutes)

This gives you a full Linux OS running inside QEMU, managed by the TPM!

**Step 1: Download Debian ISO**
```bash
# Download Debian 12 installer (about 650MB)
cd /Users/gaahrdner/Code/the-last-of-trust
wget https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-12.8.0-amd64-netinst.iso
```

**Step 2: Edit docker-compose.yaml**

Add the ISO to the host service. Find the `host:` section and add a volume:

```yaml
  host:
    build:
      context: ./Dockerfiles/host
      dockerfile: Dockerfile
    container_name: tlot-host
    networks:
      oob-net:
        ipv4_address: 10.100.0.10
      mgmt-net:
        ipv4_address: 10.101.0.10
    volumes:
      - host-data:/var/lib/host
      - ./firmware:/firmware
      - ./logs/host:/logs
      - ./debian-12.8.0-amd64-netinst.iso:/build/debian-installer.iso:ro  # ADD THIS LINE
```

**Step 3: Restart host with the ISO**
```bash
docker compose restart host
docker attach tlot-host
```

You'll see the Debian installer boot up!

**Step 4: Install Debian**

Follow the on-screen installer:
- Language: English
- Location: Your country
- Keyboard: Your layout
- Hostname: `tlot-host`
- Domain: (leave blank)
- Root password: (set something)
- User: Create a user account
- Partitioning: **Guided - use entire disk** (it's virtual, so it's safe)
- Software: Uncheck Desktop, select **SSH server** and **standard system utilities**
- Install GRUB: Yes, to `/dev/vda`

Installation takes ~10-15 minutes.

**Step 5: After installation, remove the ISO**

Edit `docker-compose.yaml` and remove the ISO line you added, then:
```bash
docker compose restart host
```

**Step 6: Access your Debian system**
```bash
# SSH into the VM (from your Mac)
ssh -p 2222 youruser@localhost

# Or attach to console
docker attach tlot-host
```

---

### 🔬 Level 3: Security Research (Advanced)

Once Debian is installed, you can do real security research:

**1. TPM Experiments**
```bash
# SSH into Debian
ssh -p 2222 youruser@localhost

# Install TPM tools
sudo apt-get update
sudo apt-get install tpm2-tools

# Read TPM PCRs (Platform Configuration Registers)
sudo tpm2_pcrread

# Take measurements
sudo tpm2_quote
```

**2. Test Measured Boot**
```bash
# Check what was measured during boot
sudo dmesg | grep -i tpm
sudo tpm2_eventlog /sys/kernel/security/tpm0/binary_bios_measurements
```

**3. Install Security Monitoring**
```bash
# Inside Debian VM:
# Install osquery for endpoint monitoring
wget https://pkg.osquery.io/deb/osquery_5.10.2-1.linux_amd64.deb
sudo dpkg -i osquery_*.deb

# Query system info
osqueryi "SELECT * FROM system_info;"
osqueryi "SELECT * FROM processes;"
```

**4. Firmware Analysis**
```bash
# Install chipsec (firmware security tool)
sudo apt-get install python3-pip
pip3 install chipsec

# Analyze firmware settings
sudo chipsec_main
```

**5. Network Security Testing**
```bash
# Test connectivity to BMC
ping 10.100.0.20  # OOB network
ping 10.101.0.20  # Management network

# Install network tools
sudo apt-get install nmap netcat tcpdump

# Scan BMC
nmap -p- 10.100.0.20
```

---

## 🎓 What Can You Actually Do?

### For Learning:
- **Firmware Security**: Study how BIOS/firmware boots
- **Trusted Computing**: Learn TPM concepts hands-on
- **Containerization**: See Docker/QEMU nested virtualization
- **Network Isolation**: Understand OOB vs management networks

### For Research:
- **Boot Process Analysis**: Study measured boot with TPM
- **Attestation**: Implement remote attestation protocols
- **Firmware Attacks**: Test firmware vulnerabilities (ethical hacking)
- **BMC Security**: Research BMC attack surfaces

### For Development:
- **Custom Firmware**: Build your own Coreboot firmware
- **Security Tools**: Develop firmware analysis tools
- **Monitoring**: Build security monitoring pipelines
- **Automation**: Create automated security testing

---

## 🔧 Common Tasks

### View Real-Time Logs
```bash
# Watch host boot
docker logs -f tlot-host

# Watch both containers
docker compose logs -f

# Just errors
docker compose logs | grep -i error
```

### Check Resource Usage
```bash
docker stats tlot-host tlot-bmc
```

### Restart Everything
```bash
docker compose restart
```

### Access QEMU Monitor Console
```bash
# Attach to QEMU
docker attach tlot-host

# At QEMU monitor, type:
info registers    # See CPU registers
info mem         # See memory
info mtree       # Memory map
quit             # Shutdown QEMU
```

### Export/Import Disk Images
```bash
# Export the Debian disk image
docker cp tlot-host:/var/lib/host/debian.qcow2 ./debian-backup.qcow2

# Import it back
docker cp ./debian-backup.qcow2 tlot-host:/var/lib/host/debian.qcow2
```

---

## 🎯 Recommended Path

**If you're new to this:**
1. Start with Level 1 (exploration) - 5 minutes
2. Install Debian (Level 2) - 30 minutes
3. Play with TPM tools (Level 3) - ongoing

**If you know what you're doing:**
- Install Debian right away
- Build custom Coreboot firmware with `dagger call firmware build-firmware`
- Set up remote attestation with Keylime
- Implement security monitoring

---

## 📊 System Architecture

```
Your Mac
  └── Docker Desktop
      ├── tlot-host container
      │   ├── QEMU (virtual computer)
      │   │   └── Debian Linux (to be installed)
      │   ├── swtpm (software TPM)
      │   └── Security tools
      │
      └── tlot-bmc container
          └── OpenBMC simulation

Networks:
  - OOB: 10.100.0.0/24 (BMC management)
  - MGMT: 10.101.0.0/24 (general access)
```

---

## 🐛 Troubleshooting

**Container keeps restarting:**
```bash
docker logs tlot-host  # Check what went wrong
```

**Can't SSH to Debian:**
- Make sure Debian is installed
- Make sure SSH server was installed during setup
- Try: `ssh -v -p 2222 user@localhost` for verbose output

**QEMU won't start:**
```bash
# Check if firmware exists
docker exec tlot-host ls -la /firmware/

# Check QEMU process
docker exec tlot-host ps aux | grep qemu
```

**TPM not working:**
```bash
# Check TPM state
docker exec tlot-host ls -la /var/lib/host/tpm/
docker exec tlot-host ps aux | grep swtpm
```

---

## 🎉 Success Criteria

You'll know it's working when:
- ✅ Containers are running: `docker compose ps`
- ✅ QEMU is booting: `docker logs tlot-host` shows boot messages
- ✅ TPM is active: Logs show TPM initialization
- ✅ (After Debian install) You can SSH in: `ssh -p 2222 user@localhost`

---

## 📚 Next Steps

- Read `CLAUDE.md` for architecture details
- Check `IMPLEMENTATION_STATUS.md` for what's complete
- See `MACOS_QUICKSTART.md` for macOS-specific tips
- Explore `Dockerfiles/` to understand how it's built

**Have fun and stay curious!** 🚀
