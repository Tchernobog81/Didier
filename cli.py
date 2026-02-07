#!/usr/bin/env python3
import argparse
from orchestrator.core import Orchestrator

def main():
    parser = argparse.ArgumentParser(description="Didier CLI")
    parser.add_argument("--db", default="data/didier.db")
    args = parser.parse_args()
    d = Orchestrator(storage_path=args.db)
    d.start()
    print("Didier démarré en mode CLI. Test rapide:")
    print(d.agent.chat("Bonjour Didier, raconte quelque chose de drôle."))

if __name__ == "__main__":
    main()
