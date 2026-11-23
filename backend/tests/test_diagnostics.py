from app.services.hardware import local_tool_status


def test_local_diagnostics_expose_boolean_tool_flags():
    status = local_tool_status()
    assert set(status) == {"ffmpeg", "nvidia_smi", "ollama"}
    assert all(isinstance(value, bool) for value in status.values())
