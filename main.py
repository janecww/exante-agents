from harness.orchestrator import Orchestrator

TECHNOLOGY = "Brown seaweed-based bioplastic"
SCALE = "4000 tonnes per year production capacity"


def main() -> None:
    orchestrator = Orchestrator(technology=TECHNOLOGY, scale=SCALE)
    orchestrator.run()


if __name__ == "__main__":
    main()
