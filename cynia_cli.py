import os
import sys
import shutil
import subprocess
import argparse
import signal
import atexit

def get_package_dir():
    """Get the directory where the package is installed."""
    return os.path.dirname(os.path.abspath(__file__))

def run_app():
    """Run the Streamlit app."""
    package_dir = get_package_dir()
    web_py_path = os.path.join(package_dir, "web.py")
    
    # Construct the command
    cmd = [sys.executable, "-m", "streamlit", "run", web_py_path]
    
    # Pass through any extra arguments to Streamlit
    if len(sys.argv) > 1 and sys.argv[1] not in ["dev"]:
         cmd.extend(sys.argv[1:])

    print(f"Starting Cynia Agents from {package_dir}...")
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nStopping Cynia Agents...")

def run_dev():
    """Run the app in dev mode with the current directory linked as a component."""
    current_dir = os.getcwd()
    component_name = os.path.basename(current_dir)
    package_dir = get_package_dir()
    components_dir = os.path.join(package_dir, "components")
    target_link = os.path.join(components_dir, component_name)

    print(f"Starting Dev Mode for component: {component_name}")
    print(f"Linking {current_dir} -> {target_link}")

    # Create symlink/junction
    if os.path.exists(target_link):
        print(f"Warning: Component '{component_name}' already exists in components folder.")
        print("Using existing component. Please ensure this is what you intended.")
        created_link = False
    else:
        try:
            if os.name == 'nt':
                # On Windows, use junction for directories
                import _winapi
                _winapi.CreateJunction(current_dir, target_link)
            else:
                os.symlink(current_dir, target_link)
            created_link = True
        except Exception as e:
            print(f"Error creating link: {e}")
            sys.exit(1)

    def cleanup():
        if created_link and os.path.exists(target_link):
            print(f"\nCleaning up link: {target_link}")
            try:
                if os.name == 'nt':
                    os.rmdir(target_link) # rmdir removes junctions
                else:
                    os.unlink(target_link)
            except Exception as e:
                print(f"Error removing link: {e}")

    # Register cleanup
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda sig, frame: sys.exit(0))

    # Run the app
    run_app()

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        run_dev()
    else:
        run_app()

if __name__ == "__main__":
    main()
