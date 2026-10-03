import argparse
import importlib

# (framework, mode) -> module that exposes run(question, employee_id) -> str
RUNNERS = {
    ("gemini_sdk", "react"): "agents.gemini_sdk.react",
    # ("gemini_sdk", "reflect"): "agents.gemini_sdk.reflect",
    # ("adk", "react"): "agents.adk_app.react",
}


def main():
    parser = argparse.ArgumentParser(description="Kestrel Works helpdesk agent")
    parser.add_argument("question")
    parser.add_argument("--employee", default="E001")
    parser.add_argument("--framework", default="gemini_sdk", choices=sorted({f for f, _ in RUNNERS}))
    parser.add_argument("--mode", default="react", choices=sorted({m for _, m in RUNNERS}))
    args = parser.parse_args()

    key = (args.framework, args.mode)
    if key not in RUNNERS:
        parser.error(f"{args.framework} does not implement '{args.mode}' yet")

    runner = importlib.import_module(RUNNERS[key])   # imported only when chosen
    print("\nANSWER:", runner.run(args.question, employee_id=args.employee))


if __name__ == "__main__":
    main()