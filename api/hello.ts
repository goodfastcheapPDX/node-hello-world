import type { VercelRequest, VercelResponse } from '@vercel/node'

import { createReadStream, createWriteStream, unlinkSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';
import { tmpdir } from 'os';
import fetch from 'node-fetch';
import FormData from 'form-data';
import { randomUUID } from 'crypto';
import ytdl from 'ytdl-core';

// Function to extract YouTube ID from URL
function extractYouTubeId(url) {
  const regex = /(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
  const match = url.match(regex);
  return match ? match[1] : null;
}

// Function to format seconds as HH:MM:SS
function formatTime(seconds) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Only allow GET requests
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // Get YouTube URL from query parameter
  const youtubeUrl = req.query.url;
  if (!youtubeUrl) {
    return res.status(400).json({ error: 'Missing YouTube URL. Use ?url=YOUTUBE_URL' });
  }

  // Extract YouTube ID
  const videoId = extractYouTubeId(youtubeUrl);
  if (!videoId) {
    return res.status(400).json({ error: 'Invalid YouTube URL' });
  }

  // Use a unique filename to avoid conflicts
  const uniqueId = randomUUID();
  const outputPath = join(tmpdir(), `youtube-audio-${uniqueId}.mp3`);

  try {
    // First, get video info to show what we're processing
    const videoInfo = await ytdl.getInfo(videoId);
    const videoTitle = videoInfo.videoDetails.title;
    
    // Download and convert YouTube audio
    console.log(`Downloading audio for: ${videoTitle}`);
    
    // Create a write stream for the output file
    const outputStream = createWriteStream(outputPath);
    
    // Download only audio in mp3 format using ytdl
    ytdl(youtubeUrl, {
      filter: 'audioonly',
      quality: 'lowestaudio',
    }).pipe(outputStream);
    
    // Wait for download to complete
    await new Promise((resolve, reject) => {
      outputStream.on('finish', resolve);
      outputStream.on('error', reject);
    });
    
    console.log('Audio download complete. Sending to Whisper API...');
    
    // Prepare to send to Whisper API
    const formData = new FormData();
    formData.append('file', createReadStream(outputPath));
    formData.append('model', 'whisper-1');
    formData.append('response_format', 'verbose_json');
    
    // Send to Whisper API
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
    
    // Get transcription result
    const transcription = await whisperResponse.json();
    
    // Add formatted transcript with timestamps
    let formattedTranscript = '';
    if (transcription.segments) {
      formattedTranscript = transcription.segments.map(segment => {
        return `[${formatTime(segment.start)} - ${formatTime(segment.end)}] ${segment.text}`;
      }).join('\n\n');
    }
    
    // Clean up the temporary file
    try {
      unlinkSync(outputPath);
    } catch (cleanupError) {
      console.error('Error cleaning up temp file:', cleanupError);
    }
    
    // Return the result
    return res.status(200).json({
      success: true,
      video: {
        id: videoId,
        title: videoTitle,
        url: youtubeUrl
      },
      transcript: {
        full: transcription.text,
        formatted: formattedTranscript,
        segments: transcription.segments
      }
    });
    
  } catch (error) {
    console.error('Error processing request:', error);
    
    // Clean up temp file if it exists
    try {
      unlinkSync(outputPath);
    } catch (cleanupError) {
      // Ignore cleanup errors
    }
    
    return res.status(500).json({
      error: error.message || 'An unknown error occurred'
    });
  }
}
