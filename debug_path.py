import os
import sys

print("--- DEBUGGING PATHS ---")
current_dir = os.path.abspath(os.path.dirname(__file__))
print(f"1. Current Directory: {current_dir}")

print("\n2. Python Path (sys.path):")
for p in sys.path:
    print(f"   - {p}")

print("\n3. Checking for Inner Package:")
inner_pkg = os.path.join(current_dir, "alpha_scanner_core")
if os.path.exists(inner_pkg):
    print(f"   ✅ Found inner folder: {inner_pkg}")
    if os.path.exists(os.path.join(inner_pkg, "__init__.py")):
        print("   ✅ Found __init__.py inside inner folder.")
    else:
        print("   ❌ MISSING __init__.py in inner folder!")
else:
    print(f"   ❌ COULD NOT FIND inner folder 'alpha_scanner_core'.")
    print("      (This means your code files might be sitting in the root, not in a subfolder)")

print("\n4. Directory Tree (First 2 levels):")
for root, dirs, files in os.walk(current_dir):
    level = root.replace(current_dir, '').count(os.sep)
    if level < 2:
        indent = ' ' * 4 * (level)
        print(f"{indent}{os.path.basename(root)}/")
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            if not f.startswith('.'):
                print(f"{subindent}{f}")
