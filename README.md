# Voice-To-Voice Farmer Advisor System

This project implements a Voice-to-Voice Farmer Advisor System that provides agricultural information to farmers in Amharic via a voice-based interface. The system uses speech-to-text (STT) to understand queries, a logic service with RAG (Retrieval-Augmented Generation) to find relevant information, and text-to-speech (TTS) to deliver responses.

## 🚀 Features

- **Amharic Speech-to-Text**: Uses OpenAI's Whisper model for accurate transcription.
- **RAG-Based Logic Service**: Retrieves information from a knowledge base using vector similarity search.
- **Amharic Text-to-Speech**: Generates natural-sounding Amharic speech.
- **Admin Dashboard**: A web interface to view escalation queues and manage the system.
- **Dockerized Deployment**: All services are containerized for easy deployment and management.

## 🛠️ Architecture

The system consists of four main services:

1.  **Telephony Service**: Handles incoming calls, audio capture, and playback.
2.  **STT Service**: Transcribes audio to text.
3.  **Logic Service**: Processes text queries, performs RAG, and generates responses.
4.  **TTS Service**: Converts text to speech.
5.  **Admin Dashboard**: A web interface for system monitoring and management.

## 📂 Project Structure

```
Voice-To-Voice-Farmer-Advisor/
├── telephony_service/      # SIP/VoIP client and audio processing
├── stt_service/            # Speech-to-text service
├── logic_service/          # RAG pipeline and business logic
├── tts_service/            # Text-to-speech service
├── admin_dashboard/        # Streamlit-based admin interface
├── data/                   # Data files (knowledge base, embeddings)
├── .env                    # Environment variables
└── docker-compose.yml      # Docker orchestration
```

## ⚙️ Prerequisites

- [Docker](https://www.docker.com/)
- [Docker Compose](https://docs.docker.com/compose/)

## 🚀 Quick Start

1.  **Clone the repository** (if not already done).

2.  **Configure Environment Variables**:
    Copy the example environment file and fill in your credentials:
    ```bash
    cp .env.example .env
    ```
    Edit `.env` with your specific configuration.

3.  **Build and Start Services**:
    ```bash
    docker-compose up --build
    ```

4.  **Access the Services**:
    - **Admin Dashboard**: [http://localhost:8501](http://localhost:8501)
    - **STT Service**: [http://localhost:8001](http://localhost:8001)
    - **Logic Service**: [http://localhost:8000](http://localhost:8000)
    - **TTS Service**: [http://localhost:8002](http://localhost:8002)
    - **Telephony Service**: [http://localhost:5060](http://localhost:5060)

## 🧪 Testing

### Test STT Service

```bash
curl -X POST http://localhost:8001/transcribe \
  -H "Content-Type: multipart/form-data" \
  -F "audio_file=@/path/to/your/audio.wav"
```

### Test Logic Service

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"text": "የግብርና መረጃ እፈልጋለሁ", "phone_number": "+251912345678", "session_id": "test_session"}'
```

### Test TTS Service

```bash
curl -X POST http://localhost:8002/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "ሰላም! እንዴት ልርዳዎት?"}' \
  -o response.mp3
```

## 📂 Service Details

### Telephony Service

Handles SIP communication and audio streaming. Currently configured for local testing but can be connected to a SIP server.

### STT Service

Uses OpenAI's Whisper model for Amharic speech recognition. Runs on port 8001.

### Logic Service

Implements the RAG pipeline with ChromaDB for vector search. Runs on port 8000.

### TTS Service

Uses gTTS for Amharic text-to-speech. Runs on port 8002.

### Admin Dashboard

Provides a web interface for:
- Viewing escalation queues
- Monitoring system health
- Accessing logs

## 🤝 Contributing

1.  Create a feature branch (`git checkout -b feature/AmazingFeature`).
2.  Commit your changes (`git commit -m 'Add some AmazingFeature'`).
3.  Push to the branch (`git push origin feature/AmazingFeature`).
4.  Open a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.