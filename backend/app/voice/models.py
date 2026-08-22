from pydantic import BaseModel, Field

class AudioFormat(BaseModel):
    codec: str = Field(..., description="Audio codec, e.g., 'pcm', 'opus', 'ulaw'")
    sample_rate: int = Field(..., description="Sample rate in Hz, e.g., 16000, 24000")
    channels: int = Field(..., description="Number of channels, typically 1 or 2")

class VoiceConfig(BaseModel):
    input_format: AudioFormat
    output_format: AudioFormat
