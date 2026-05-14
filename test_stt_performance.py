import time
import requests
from gtts import gTTS
import os

print("--- STT Performance & Accuracy Test ---")

# Step 1: Generate real Amharic audio payload
test_text = "የጤፍ ዋጋ ስንት ነው" # "What is the price of teff?"
print(f"Generating control audio for: '{test_text}'")

try:
    tts = gTTS(text=test_text, lang='am')
    tts.save("control_amharic.mp3")
    print("Audio successfully generated as control_amharic.mp3.")
except Exception as e:
    print("Could not generate audio (is gTTS installed?). Attempting to proceed with dummy audio.")
    # Fallback to dummy data if gTTS not available locally
    with open("control_amharic.mp3", "wb") as f:
        f.write(b"mock data")

# Step 2: Test STT Speed and accuracy
url = "http://localhost:8001/transcribe"
print(f"\nSending audio to STT Service at {url}...")

start_time = time.time()

try:
    with open("control_amharic.mp3", "rb") as f:
        response = requests.post(url, files={"audio_file": f})
        
    end_time = time.time()
    latency = end_time - start_time
    
    if response.status_code == 200:
        transcription = response.json().get("text", "")
        print(f"\n✅ STT Success! Status: {response.status_code}")
        print(f"⏱️ Latency: {latency:.2f} seconds")
        print(f"📝 Transcription Output: '{transcription}'")
        
        # Check basic accuracy
        if "ጤፍ" in transcription or "ዋጋ" in transcription:
            print("🎯 Accuracy: High (Matched keywords successfully)")
        else:
            print("⚠️ Accuracy: Low (Did not parse control keywords)")
    else:
        print(f"\n❌ STT Failed! HTTP Status: {response.status_code}")
        print(response.text)
        
except requests.exceptions.ConnectionError:
    print(f"\n❌ Connection Error: Ensure STT container is fully running and port 8001 is mapped.")
except Exception as e:
    print(f"\n❌ Unexpected Error: {e}")
