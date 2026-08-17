from python_agent_forge.main import main


def test_main_succeeds() -> None:
    assert main() == 0
