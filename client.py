import requests
import json
import time

# Create a mock raw audio file since we don't have mic input in Docker script
with open("test_audio.wav", "wb") as f:
    f.write(b"mock audio structure for testing...")

print("---- Initiating Voice-To-Voice Call Request ----")

# 1. Send Audio to STT Service
print("1. Sending incoming Amharic audio to STT Service...")
try:
    with open("test_audio.wav", "rb") as f:
        stt_response = requests.post("http://localhost:8001/transcribe", files={"audio_file": f})
    
    transcribed_text = stt_response.json().get("text")
    print(f" -> STT Result: {transcribed_text}")
except Exception as e:
    print(f"Failed to connect to STT service: {e}")
    exit(1)

# 2. Send Text to Logic/RAG Service
print("\n2. Sending transcribed text to Logic/RAG Server...")
logic_payload = {"text": transcribed_text}
try:
    logic_response = requests.post("http://localhost:8002/ask", json=logic_payload)
    logic_data = logic_response.json()
    response_text = logic_data.get("response")
    intent = logic_data.get("intent")
    print(f" -> Identified Intent: {intent}")
    print(f" -> RAG Output: {response_text}")
except Exception as e:
    print(f"Failed to connect to Logic service: {e}")
    exit(1)

# 3. Send Text to TTS Service
print("\n3. Sending RAG output to TTS Service...")
tts_payload = {"text": response_text}
try:
    tts_response = requests.post("http://localhost:8003/synthesize", json=tts_payload)
    if tts_response.status_code == 200:
        with open("final_advisor_response.mp3", "wb") as f:
            f.write(tts_response.content)
        print(" -> Output Audio locally saved as 'final_advisor_response.mp3'")
        print("\n---- Call Completed Successfully! ----")
    else:
        print(f" -> Failed. TTS Service returned {tts_response.status_code}")
except Exception as e:
    print(f"Failed to connect to TTS service: {e}")
    exit(1)
