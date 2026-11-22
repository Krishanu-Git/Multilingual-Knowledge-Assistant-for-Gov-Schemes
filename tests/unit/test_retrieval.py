from government_assistant.retrieval import retrieve

def test_bm25_retrieves_exact_match_across_unicode():
    docs=[{"content":"PM Kisan income support for farmers","scheme_id":"a","chunk_id":"1"},{"content":"छात्रवृत्ति विद्यार्थियों के लिए","scheme_id":"b","chunk_id":"2"}]
    assert retrieve("PM Kisan farmers",docs)[0]["scheme_id"]=="a"

def test_state_filter_keeps_central_scheme():
    docs=[{"content":"farmer support scheme","scheme_id":"c","state":None,"scheme_level":"Central"},{"content":"farmer scheme","scheme_id":"x","state":"Other","scheme_level":"State"}]
    assert retrieve("farmer support",docs,filters={"state":"Assam"})[0]["scheme_id"]=="c"
