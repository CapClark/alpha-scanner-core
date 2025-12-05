# This file sits at the root of your project.
# It automatically sets up the path so Python can find your code.

import sys
import os

# 1. Add the current directory (project root) to Python's path
# This ensures 'alpha_scanner_core' is treated as a top-level package
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print(f"🚀 Launching Alpha Scanner from: {project_root}")

# 2. Import your main CLI function inside a try-block to catch import errors early
try:
    from alpha_scanner_core.cli.main import main
except ImportError as e:
    print("❌ Error importing the application.")
    print(f"   Details: {e}")
    print("\n   Troubleshooting:")
    print("   1. Check that 'alpha_scanner_core' folder exists in this directory.")
    print("   2. Check that 'alpha_scanner_core/__init__.py' exists.")
    print("   3. Make sure you are running 'python run.py' from the root folder.")
    sys.exit(1)

if __name__ == "__main__":
    # 3. Run the app
    main()