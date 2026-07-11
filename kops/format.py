import sys
import subprocess


def main() -> None:
    cmd = ["ruff", "format"] + sys.argv[1:]
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
