import os
import json
import subprocess
import platform
import re

class LinuxGatherer:
    def __init__(self):
        pass

    def get_command_output(self, command):
        try:
            return subprocess.check_output(command, shell=True, stderr=subprocess.DEVNULL).decode('utf-8')
        except:
            return ""

    def get_sys_attr(self, path):
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    return f.read().strip()
        except:
            pass
        return ""

    def parse_lspci(self):
        devices = []
        output = self.get_command_output("lspci -nn -vmm")
        current_device = {}
        for line in output.splitlines():
            if not line.strip():
                if current_device:
                    devices.append(current_device)
                    current_device = {}
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                current_device[key.strip()] = value.strip()
        if current_device:
            devices.append(current_device)
        return devices

    def get_pci_path(self, slot):
        # slot is like 00:02.0
        try:
            bus, device_function = slot.split(":")
            device, function = device_function.split(".")
            # Most common is PciRoot(0x0)
            return f"PciRoot(0x{int(bus, 16)})/Pci(0x{int(device, 16)},0x{int(function, 16)})"
        except:
            pass
        return ""

    def gather_report(self):
        report = {
            "Motherboard": {
                "Name": "Unknown",
                "Chipset": "Unknown",
                "Platform": "Desktop"
            },
            "BIOS": {
                "Version": "Unknown",
                "Release Date": "Unknown",
                "System Type": "x64",
                "Firmware Type": "UEFI",
                "Secure Boot": "Disabled"
            },
            "CPU": {
                "Manufacturer": "Unknown",
                "Processor Name": "Unknown",
                "Codename": "Unknown",
                "Core Count": "0",
                "CPU Count": "1",
                "SIMD Features": ""
            },
            "GPU": {},
            "Monitor": {},
            "Network": {},
            "Sound": {},
            "USB Controllers": {},
            "Input": {},
            "Storage Controllers": {},
            "Bluetooth": {},
            "SD Controller": {},
            "System Devices": {}
        }

        # Motherboard & BIOS
        report["Motherboard"]["Name"] = self.get_sys_attr("/sys/class/dmi/id/board_name") or self.get_sys_attr("/sys/class/dmi/id/product_name") or "Unknown"
        
        # Chipset detection (crude)
        lspci_output = self.get_command_output("lspci")
        chipset_match = re.search(r"Host bridge:.*?\s([A-Z][0-9]+|LPC)", lspci_output)
        if chipset_match:
            report["Motherboard"]["Chipset"] = chipset_match.group(1)

        chassis_type = self.get_sys_attr("/sys/class/dmi/id/chassis_type")
        if chassis_type in ["8", "9", "10", "11", "12", "14", "30", "31", "32"]:
            report["Motherboard"]["Platform"] = "Laptop"
        else:
            report["Motherboard"]["Platform"] = "Desktop"

        report["BIOS"]["Version"] = self.get_sys_attr("/sys/class/dmi/id/bios_version") or "Unknown"
        report["BIOS"]["Release Date"] = self.get_sys_attr("/sys/class/dmi/id/bios_date") or "Unknown"
        report["BIOS"]["Firmware Type"] = "UEFI" if os.path.exists("/sys/firmware/efi") else "BIOS"
        
        secure_boot = self.get_command_output("bootctl status")
        if "Secure Boot: enabled" in secure_boot:
            report["BIOS"]["Secure Boot"] = "Enabled"
        else:
            report["BIOS"]["Secure Boot"] = "Disabled"

        # CPU
        cpu_info = self.get_command_output("lscpu")
        for line in cpu_info.splitlines():
            if "Vendor ID:" in line:
                vendor = line.split(":")[1].strip()
                report["CPU"]["Manufacturer"] = "Intel" if "Intel" in vendor else "AMD" if "AuthenticAMD" in vendor else vendor
            if "Model name:" in line:
                report["CPU"]["Processor Name"] = line.split(":")[1].strip()
        
        if not report["CPU"].get("Processor Name") or report["CPU"].get("Processor Name") == "Unknown":
            # Try to get it from /proc/cpuinfo if lscpu failed
            cpu_name = self.get_command_output("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2").strip()
            if cpu_name:
                report["CPU"]["Processor Name"] = cpu_name

        cpu_flags = self.get_command_output("grep -m1 flags /proc/cpuinfo")
        if ":" in cpu_flags:
            flags = cpu_flags.split(":")[1].strip().split()
            simd = []
            if "sse4_1" in flags: simd.append("SSE4.1")
            if "sse4_2" in flags: simd.append("SSE4.2")
            if "avx" in flags: simd.append("AVX")
            if "avx2" in flags: simd.append("AVX2")
            if "ssse3" in flags: simd.append("SSSE3")
            # If nothing matched but we have sse, just add it for visibility
            if not simd:
                report["CPU"]["SIMD Features"] = " ".join(flags).upper()
            else:
                report["CPU"]["SIMD Features"] = ", ".join(simd)

        # Try to get Codename from inxi
        inxi_output = self.get_command_output("inxi -C")
        codename_match = re.search(r"arch: ([\w\s]+)", inxi_output)
        if codename_match:
            report["CPU"]["Codename"] = codename_match.group(1).strip()

        # PCI Devices
        pci_devices = self.parse_lspci()
        counts = {"GPU": 0, "Network": 0, "Sound": 0, "USB": 0, "Storage": 0, "System": 0, "SD": 0}

        for dev in pci_devices:
            cls = dev.get("Class", "").lower()
            vendor_id = ""
            device_id = ""
            if "Vendor" in dev and "[" in dev["Vendor"]:
                vendor_id = dev["Vendor"].split("[")[1].split("]")[0]
            if "Device" in dev and "[" in dev["Device"]:
                device_id = dev["Device"].split("[")[1].split("]")[0]
            
            if not vendor_id or not device_id: continue
            
            full_id = f"{vendor_id.upper()}-{device_id.upper()}"
            slot = dev.get("Slot", "")
            pci_path = self.get_pci_path(slot)

            if "vga" in cls or "display" in cls or "3d" in cls:
                name = f"GPU {counts['GPU']}"
                report["GPU"][name] = {
                    "Manufacturer": "Intel" if "8086" in vendor_id else "AMD" if "1002" in vendor_id else "NVIDIA" if "10de" in vendor_id else "Unknown",
                    "Codename": dev.get("Device", "").split("[")[0].strip(),
                    "Device ID": full_id,
                    "Device Type": "Integrated GPU" if "8086" in vendor_id and "vga" in cls else "Discrete GPU",
                    "PCI Path": pci_path
                }
                counts['GPU'] += 1
            
            elif "ethernet" in cls or "network" in cls or "wireless" in cls:
                name = f"Network {counts['Network']}"
                report["Network"][name] = {
                    "Bus Type": "PCI",
                    "Device ID": full_id,
                    "PCI Path": pci_path
                }
                counts['Network'] += 1
            
            elif "audio" in cls or "multimedia" in cls:
                name = f"Sound {counts['Sound']}"
                report["Sound"][name] = {
                    "Bus Type": "PCI",
                    "Device ID": full_id,
                    "PCI Path": pci_path
                }
                counts['Sound'] += 1

            elif "usb" in cls:
                name = f"USB Controller {counts['USB']}"
                report["USB Controllers"][name] = {
                    "Bus Type": "PCI",
                    "Device ID": full_id,
                    "PCI Path": pci_path
                }
                counts['USB'] += 1

            elif "sata" in cls or "nvme" in cls or "mass storage" in cls:
                name = f"Storage Controller {counts['Storage']}"
                report["Storage Controllers"][name] = {
                    "Bus Type": "PCI",
                    "Device ID": full_id,
                    "PCI Path": pci_path
                }
                counts['Storage'] += 1
            
            elif "sd host" in cls:
                name = f"SD Controller {counts['SD']}"
                report["SD Controller"][name] = {
                    "Bus Type": "PCI",
                    "Device ID": full_id,
                    "PCI Path": pci_path
                }
                counts['SD'] += 1
            
            else:
                name = f"System Device {counts['System']}"
                report["System Devices"][name] = {
                    "Bus Type": "PCI",
                    "Device ID": full_id,
                    "PCI Path": pci_path,
                    "Device": dev.get("Device", "").split("[")[0].strip()
                }
                counts['System'] += 1

        # Bluetooth
        lsusb = self.get_command_output("lsusb")
        bt_count = 0
        for line in lsusb.splitlines():
            if "bluetooth" in line.lower():
                bt_id_match = re.search(r"ID ([0-9a-fA-F]{4}):([0-9a-fA-F]{4})", line)
                if bt_id_match:
                    bt_id = f"{bt_id_match.group(1).upper()}-{bt_id_match.group(2).upper()}"
                    report["Bluetooth"][f"Bluetooth {bt_count}"] = {
                        "Bus Type": "USB",
                        "Device ID": bt_id
                    }
                    bt_count += 1

        # Input
        input_devices = self.get_command_output("cat /proc/bus/input/devices")
        input_count = 0
        current_input = {}
        for line in input_devices.splitlines():
            if not line.strip():
                if "Name" in current_input:
                    name = current_input["Name"]
                    bus_type = "USB" if "bus=0003" in current_input.get("I", "").lower() else "ACPI" if "bus=0011" in current_input.get("I", "").lower() else "ROOT"
                    report["Input"][f"Input {input_count}"] = {
                        "Bus Type": bus_type,
                        "Device": name,
                        "Device Type": "Keyboard" if "kbd" in current_input.get("H", "").lower() else "Mouse" if "mouse" in current_input.get("H", "").lower() else "Unknown"
                    }
                    input_count += 1
                current_input = {}
                continue
            if line.startswith("N: Name="):
                current_input["Name"] = line.split('"')[1]
            if line.startswith("I: "):
                current_input["I"] = line
            if line.startswith("H: "):
                current_input["H"] = line

        return report

    def dump_acpi(self, target_dir):
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        
        acpi_tables_dir = "/sys/firmware/acpi/tables"
        if not os.path.exists(acpi_tables_dir):
            return False

        allowed_signatures = ["DSDT", "SSDT", "APIC", "DMAR"]

        # Use subprocess to copy files with sudo since we can't read them directly
        for table in os.listdir(acpi_tables_dir):
            table_path = os.path.join(acpi_tables_dir, table)
            if not os.path.isfile(table_path):
                continue

            sig = table.upper()
            sig_base = "".join([i for i in sig if not i.isdigit()])
            
            if sig_base in allowed_signatures or sig in allowed_signatures:
                target_path = os.path.join(target_dir, f"{sig}.aml")
                try:
                    # Copy and then change ownership so we can read it
                    subprocess.run(["sudo", "cp", table_path, target_path], check=True, stderr=subprocess.DEVNULL)
                    import getpass
                    subprocess.run(["sudo", "chown", getpass.getuser(), target_path], check=True, stderr=subprocess.DEVNULL)
                except:
                    pass
        
        # Check dynamic tables too
        dynamic_dir = os.path.join(acpi_tables_dir, "dynamic")
        if os.path.exists(dynamic_dir):
            for table in os.listdir(dynamic_dir):
                table_path = os.path.join(dynamic_dir, table)
                if not os.path.isfile(table_path):
                    continue
                
                sig = table.upper()
                sig_base = "".join([i for i in sig if not i.isdigit()])
                if sig_base in allowed_signatures or sig in allowed_signatures:
                    # For dynamic tables, we might want to avoid name collisions
                    target_path = os.path.join(target_dir, f"{sig}_DYN.aml")
                    try:
                        subprocess.run(["sudo", "cp", table_path, target_path], check=True, stderr=subprocess.DEVNULL)
                        import getpass
                        subprocess.run(["sudo", "chown", getpass.getuser(), target_path], check=True, stderr=subprocess.DEVNULL)
                    except:
                        pass
        return True
