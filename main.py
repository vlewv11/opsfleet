import argparse

from src.cli.chat import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retail analytics chat assistant")
    parser.add_argument("--user", default="manager_a", help="manager identity for preferences and reports")
    run(parser.parse_args().user)
