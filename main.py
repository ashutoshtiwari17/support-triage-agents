import argparse

from agents.registry import RUNNERS, load_runner


def main():
    parser = argparse.ArgumentParser(description="Kestrel Works helpdesk agent")
    parser.add_argument("question")
    parser.add_argument("--employee", default="E001")
    parser.add_argument("--framework", default="gemini_sdk", choices=sorted({f for f, _ in RUNNERS}))
    parser.add_argument("--mode", default="react", choices=sorted({m for _, m in RUNNERS}))
    args = parser.parse_args()

    if (args.framework, args.mode) not in RUNNERS:
        parser.error(f"{args.framework} does not implement '{args.mode}' yet")

    runner = load_runner(args.framework, args.mode)
    print("\nANSWER:", runner.run(args.question, employee_id=args.employee))


if __name__ == "__main__":
    main()
