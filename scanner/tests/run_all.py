import sys
from vm.manage import TestVM

if __name__ == "__main__":
    vm = TestVM()
    PYTEST_ARGS = " ".join(sys.argv[1:])
    vm.run_cmd(f"pytest /scanner/tests/tests.py {PYTEST_ARGS}", check=False)
    print("All tests executed.")
