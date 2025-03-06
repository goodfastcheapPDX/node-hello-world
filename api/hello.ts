// api/transcribe.js
import fetch from 'isomorphic-fetch';
import FormData from 'form-data';

export default async function handler(req, res) {
  // Get video ID
  const videoId = req.query.id;
  if (!videoId) {
    return res.status(400).json({ error: 'Missing video ID. Use ?id=VIDEO_ID' });
  }

  try {
    console.log(`Processing video ${videoId}...`);
    
    // Step 1: Get video info from public oEmbed API (no rate limits)
    const videoInfoUrl = `https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=${videoId}&format=json`;
    const videoInfoResponse = await fetch(videoInfoUrl);
    
    if (!videoInfoResponse.ok) {
      throw new Error(`Failed to fetch video info: ${videoInfoResponse.status}`);
    }
    
    const videoInfo = await videoInfoResponse.json();
    const videoTitle = videoInfo.title || 'Unknown Video';
    
    console.log(`Got video title: ${videoTitle}`);
    
    // Step 2: Use a public API to get direct audio URL
    // Option A: y2mate-api (adjust as needed based on reliability)
    const audioApiUrl = `https://y2mate-api-js.vercel.app/api/mp3?url=https://www.youtube.com/watch?v=${videoId}`;
    
    console.log(`Fetching audio URL from public API...`);
    const audioResponse = await fetch(audioApiUrl);
    
    if (!audioResponse.ok) {
      throw new Error(`Failed to get audio URL: ${audioResponse.status}`);
    }
    
    const audioData = await audioResponse.json();
    
    if (!audioData.success || !audioData.url) {
      throw new Error(`Audio API did not return a valid URL: ${JSON.stringify(audioData)}`);
    }
    
    const audioUrl = audioData.url;
    console.log(`Got audio URL: ${audioUrl}`);
    
    // Step 3: Download the audio file
    console.log(`Downloading audio...`);
    const audioFileResponse = await fetch(audioUrl);
    
    if (!audioFileResponse.ok) {
      throw new Error(`Failed to download audio: ${audioFileResponse.status}`);
    }
    
    const audioBuffer = await audioFileResponse.buffer();
    console.log(`Downloaded audio file, size: ${audioBuffer.length} bytes`);
    
    // Step 4: Send to Whisper API
    console.log(`Sending to Whisper API...`);
    const formData = new FormData();
    formData.append('file', audioBuffer, { filename: `${videoId}.mp3` });
    formData.append('model', 'whisper-1');
    formData.append('response_format', 'verbose_json');
    
    const whisperResponse = await fetch('https://api.openai.com/v1/audio/transcriptions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`
      },
      body: formData
    });
    
    if (!whisperResponse.ok) {
      const errorText = await whisperResponse.text();
      throw new Error(`Whisper API error: ${whisperResponse.status} - ${errorText}`);
    }
    
    // Step 5: Process and return the transcript
    const transcription = await whisperResponse.json();
    
    // Format the transcript with timestamps
    let formattedTranscript = '';
    if (transcription.segments) {
      formattedTranscript = transcription.segments.map(segment => {
        // Format timestamp to HH:MM:SS
        const startTime = formatTime(segment.start);
        const endTime = formatTime(segment.end);
        return `[${startTime} - ${endTime}] ${segment.text}`;
      }).join('\n\n');
    }
    
    return res.status(200).json({
      success: true,
      video: {
        id: videoId,
        title: videoTitle,
        url: `https://www.youtube.com/watch?v=${videoId}`
      },
      transcript: {
        full: transcription.text,
        formatted: formattedTranscript,
        segments: transcription.segments,
        source: 'whisper'
      }
    });
    
  } catch (error) {
    console.error('Error processing request:', error);
    return res.status(500).json({
      error: error.message || 'An unknown error occurred'
    });
  }
}

// Helper function to format seconds as HH:MM:SS
function formatTime(seconds) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}
