from government_assistant.generation import valid_citations

def test_invalid_citations_are_discarded():
    assert valid_citations("Claim [1], fake [2]",[{}])==[1]
