"""Seed either the local demo or a configured Lakebase database."""

import argparse

from .search import LakebaseSearchStore, LocalDemoStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["local", "lakebase"], default="local")
    parser.add_argument("--db", default=":memory:")
    args = parser.parse_args()
    if args.backend == "lakebase":
        store = LakebaseSearchStore()
        store.seed()
        print("Seeded Lakebase and built lakebase_ann + lakebase_bm25 indexes.")
    else:
        store = LocalDemoStore(args.db)
        store.seed()
        print(f"Seeded local SQLite demo at {args.db}.")


if __name__ == "__main__":
    main()
