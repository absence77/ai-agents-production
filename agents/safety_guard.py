import sys
import subprocess

# This script acts as a safety layer between the user and the Kubernetes cluster.
# It prevents accidental deletion of critical production resources.

def check_command(command):
    # List of critical keywords that could destroy the environment
    critical_keywords = ["delete", "remove", "terminate"]
    # List of protected namespaces
    protected_namespaces = ["production", "kube-system", "default"]

    cmd_string = " ".join(command).lower()

    # Check if the command contains a destructive action in a protected namespace
    is_critical = any(kw in cmd_string for kw in critical_keywords)
    is_protected = any(ns in cmd_string for ns in protected_namespaces)

    if is_critical and is_protected:
        print("\n" + "!"*50)
        print("CRITICAL WARNING: You are trying to delete resources in PRODUCTION!")
        print(f"Command: {cmd_string}")
        print("!"*50)
        
        # Require manual confirmation from the human engineer
        confirm = input("\nAre you absolutely sure you want to proceed? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Action cancelled by Safety Guard. Your infrastructure is safe.")
            sys.exit(1)

    # If the command is safe or confirmed, execute it
    try:
        result = subprocess.run(command, check=True)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # We skip the first argument as it is the script name itself
        check_command(sys.argv[1:])
    else:
        print("Usage: python3 safety_guard.py kubectl delete namespace production")
