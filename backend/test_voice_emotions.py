import sys
import os

backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

def test_oral_cleaning():
    from main import _clean_text_for_tts
    
    # Test 1: Laughter conversion
    sample1 = "*giggles softly* Oh stop it, you are so silly! *chuckles warmly*"
    cleaned1 = _clean_text_for_tts(sample1, preserve_oral_tags=True)
    print("Test 1 (Laughter):", cleaned1)
    assert "[laugh]" in cleaned1, f"Expected [laugh] in: {cleaned1}"
    assert "*" not in cleaned1, f"Asterisks should be stripped: {cleaned1}"

    # Test 2: Sighs and breath pauses
    sample2 = "*sighs softly* It was such a long day... but I am so happy to see you. (sighs deeply)"
    cleaned2 = _clean_text_for_tts(sample2, preserve_oral_tags=True)
    print("Test 2 (Sighs & pauses):", cleaned2)
    assert "[sigh]" in cleaned2, f"Expected [sigh] in: {cleaned2}"
    assert "[break_3]" in cleaned2, f"Expected [break_3] in: {cleaned2}"
    assert "*" not in cleaned2, f"Asterisks should be stripped: {cleaned2}"

    # Test 3: Action asterisks removed while keeping oral tag
    sample3 = "*looks at screen* Look at this: *giggles* isn't it wonderful? *blushes*"
    cleaned3 = _clean_text_for_tts(sample3, preserve_oral_tags=True)
    print("Test 3 (Action removal):", cleaned3)
    assert "[laugh]" in cleaned3
    assert "looks at screen" not in cleaned3
    assert "blushes" not in cleaned3

    # Test 4: Default mode (preserve_oral_tags=False) strips oral brackets
    sample4 = "Hello there! [laugh] *smiles warmly*"
    cleaned4 = _clean_text_for_tts(sample4, preserve_oral_tags=False)
    print("Test 4 (Default strip):", cleaned4)
    assert "[laugh]" not in cleaned4
    assert "*" not in cleaned4
    print("===> All Oral Cleaning Tests Passed!")

def test_chattts_mood_presets():
    from engines.tts_chattts import ChatTTSEngine, MOOD_PRESETS
    from engines.user_profile import user_profile

    # Test available moods
    moods = ChatTTSEngine.get_available_moods()
    assert len(moods) == 4
    mood_ids = [m["id"] for m in moods]
    assert "affectionate" in mood_ids
    assert "playful" in mood_ids
    assert "soothing" in mood_ids
    assert "calm" in mood_ids

    # Test engine mood switching (mocking model state if needed)
    engine = ChatTTSEngine.__new__(ChatTTSEngine)
    engine._mood = "affectionate"
    engine._lock = None
    engine._chat = None
    engine._initialized = False

    assert engine.get_mood() == "affectionate"
    ok = engine.set_mood("playful")
    assert ok is True
    assert engine.get_mood() == "playful"
    assert user_profile.get_preference("selected_mood") == "playful"

    bad = engine.set_mood("angry_robot")
    assert bad is False
    assert engine.get_mood() == "playful"
    print("===> All ChatTTS Mood Presets Tests Passed!")

def test_api_mood_routes():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)

    # GET /api/voice/mood
    resp = client.get("/api/voice/mood")
    assert resp.status_code == 200, f"Failed GET /api/voice/mood: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "active_mood" in data
    assert "moods" in data
    assert len(data["moods"]) == 4
    print("GET /api/voice/mood:", data["active_mood"], len(data["moods"]))

    # POST /api/voice/mood - valid
    post_resp = client.post("/api/voice/mood", json={"mood": "soothing"})
    assert post_resp.status_code == 200, f"Failed POST: {post_resp.status_code} {post_resp.text}"
    pdata = post_resp.json()
    assert pdata["success"] is True
    assert pdata["active_mood"] == "soothing"
    assert pdata["preset"]["id"] == "soothing"

    # POST /api/voice/mood - invalid
    err_resp = client.post("/api/voice/mood", json={"mood": "invalid_xyz"})
    assert err_resp.status_code == 400
    print("===> All API Mood Route Tests Passed!")

if __name__ == "__main__":
    test_oral_cleaning()
    test_chattts_mood_presets()
    test_api_mood_routes()
    print("\nALL VERIFICATION TESTS COMPLETED SUCCESSFULLY!")
