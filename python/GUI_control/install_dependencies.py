#!/usr/bin/env python
"""
Installation helper for DIY EEG/BCI GUI dependencies
Checks for required packages with version validation
Works on Windows/Mac/Linux

Usage: python install_dependencies.py
"""

import sys
import subprocess
import os
from importlib.metadata import version, PackageNotFoundError

def check_package_version(package_name, min_version=None):
    """Check if a package is installed with minimum version."""
    try:
        installed_version = version(package_name)
        if min_version:
            # Simple version comparison
            from packaging.version import parse
            return parse(installed_version) >= parse(min_version)
        return True
    except (PackageNotFoundError, ImportError):
        return False
    except Exception:
        # If packaging isn't available, do basic string comparison
        if min_version:
            return installed_version >= min_version
        return True

def install_package(package_spec):
    """Install a package using pip."""
    subprocess.check_call([sys.executable, "-m", "pip", "install", package_spec])

def upgrade_pip():
    """Upgrade pip to latest version."""
    try:
        print("Upgrading pip to latest version...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✓ pip upgraded")
    except:
        print("⚠ Could not upgrade pip (may cause issues with old pip versions)")

def is_interactive():
    """Check if running in interactive mode (not CI/automated)."""
    return sys.stdin.isatty() if hasattr(sys.stdin, 'isatty') else False

def parse_requirement(req_spec):
    """Parse a requirement specification like 'numpy>=1.26.0'."""
    for op in ['>=', '==', '<=', '>', '<', '~=']:
        if op in req_spec:
            name, version = req_spec.split(op, 1)
            return name.strip(), op, version.strip()
    return req_spec.strip(), None, None

def main():
    print("="*60)
    print("DIY EEG/BCI GUI - Dependency Installer")
    print("="*60)
    print(f"Python version: {sys.version}")
    print("-" * 60)
    
    # Upgrade pip first for better wheel support
    upgrade_pip()
    print()
    
    # Check tkinter (comes with Python)
    print("Checking built-in dependencies:")
    try:
        import tkinter
        print("✓ tkinter is available")
    except ImportError:
        print("✗ tkinter is missing!")
        print("  Windows: Run the Python installer again → Modify → enable 'Tcl/Tk and IDLE'")
        print("  macOS: Should be included; reinstall Python from python.org if missing")
        print("  Debian/Ubuntu: sudo apt-get install python3-tk")
        print("  Fedora: sudo dnf install python3-tkinter")
        print("  Arch/Manjaro: sudo pacman -S tk")
        sys.exit(1)
    
    # Required packages with minimum versions
    required = [
        'numpy>=1.26.0',
        'scipy>=1.11.0', 
        'matplotlib>=3.7.0',
    ]
    
    # Optional packages
    optional = [
        'pyserial>=3.5.0',
    ]
    
    print("\nChecking required packages:")
    missing_required = []
    outdated_required = []
    
    for req_spec in required:
        pkg_name, op, min_ver = parse_requirement(req_spec)
        
        if not check_package_version(pkg_name):
            print(f"✗ {pkg_name} is not installed")
            missing_required.append(req_spec)
        elif min_ver and not check_package_version(pkg_name, min_ver):
            try:
                current = version(pkg_name)
                print(f"⚠ {pkg_name} is outdated (have {current}, need >={min_ver})")
                outdated_required.append(req_spec)
            except:
                print(f"⚠ {pkg_name} version unknown, will upgrade")
                outdated_required.append(req_spec)
        else:
            try:
                current = version(pkg_name)
                print(f"✓ {pkg_name} {current} is installed")
            except:
                print(f"✓ {pkg_name} is installed")
    
    print("\nChecking optional packages:")
    missing_optional = []
    for req_spec in optional:
        pkg_name, op, min_ver = parse_requirement(req_spec)
        
        if not check_package_version(pkg_name):
            print(f"✗ {pkg_name} is not installed (optional - needed for serial ports)")
            missing_optional.append(req_spec)
        else:
            try:
                current = version(pkg_name)
                print(f"✓ {pkg_name} {current} is installed")
            except:
                print(f"✓ {pkg_name} is installed")
    
    # Install/upgrade missing or outdated required packages
    to_install = missing_required + outdated_required
    if to_install:
        print("\n" + "="*60)
        print("Installing/upgrading REQUIRED packages...")
        for package in to_install:
            print(f"Installing {package}...")
            try:
                install_package(package)
                print(f"✓ {package} installed successfully")
            except Exception as e:
                print(f"✗ Failed to install {package}: {e}")
                print("\nTry manually: pip install -r requirements.txt")
                sys.exit(1)
    
    # Ask about optional packages (only in interactive mode)
    if missing_optional:
        print("\n" + "="*60)
        print("Optional packages for serial port support are missing")
        
        if is_interactive():
            response = input("Install optional packages? (y/N): ").lower().strip()
            install_optional = response == 'y'
        else:
            print("(Skipping optional packages in non-interactive mode)")
            print("To install later: pip install pyserial")
            install_optional = False
            
        if install_optional:
            for package in missing_optional:
                print(f"Installing {package}...")
                try:
                    install_package(package)
                    print(f"✓ {package} installed successfully")
                except Exception as e:
                    print(f"✗ Failed to install {package}: {e}")
                    print("  Serial port features will be unavailable")
    
    print("\n" + "="*60)
    if not to_install:
        print("✓ All required dependencies are installed and up to date!")
    else:
        print("✓ Required dependencies have been installed!")
    print("\nYou can now run: python main_gui.py")
    print("\nFor serial port support: pip install pyserial")

if __name__ == "__main__":
    main()