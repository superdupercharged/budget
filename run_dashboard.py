"""
Launch the Budget Dashboard.

Usage:
    python run_dashboard.py           # http://localhost:8000
    python run_dashboard.py --port 8080
"""
import argparse
import os
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    # Change to workspace root so relative paths (budget_dict.json, statements/) resolve
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, "dashboard")

    import uvicorn
    uvicorn.run(
        "dashboard.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )

if __name__ == "__main__":
    main()
