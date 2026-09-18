import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'

/**
 * Press-to-talk microphone (T1.32's "mic button + text fallback").
 *
 * Records from the browser with MediaRecorder, hands the clip up as base64,
 * and gets out of the way. Two constraints shape it:
 *
 *  - Sarvam's REST speech-to-text takes 30 seconds of audio per request, so
 *    recording stops itself at MAX_SECONDS rather than letting someone talk
 *    into a request that will be rejected.
 *  - Microphone access needs a user gesture and can be denied outright. A
 *    refusal is reported to the parent so the page can say so plainly and
 *    fall back to typing, rather than leaving a dead button on screen.
 *
 * While recording, the label is replaced by a live waveform — the one place
 * the design lets the accent colour move, and the clearest possible signal
 * that the microphone is actually open.
 */
const MAX_SECONDS = 25          // Sarvam's REST limit is 30s; stop short of it.

export default function MicButton({ onClip, disabled, onUnavailable }) {
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [supported, setSupported] = useState(true)
  const recorderRef = useRef(null)
  const chunksRef = useRef([])
  const timerRef = useRef(null)
  const streamRef = useRef(null)

  useEffect(() => {
    const ok = typeof window !== 'undefined'
      && !!navigator.mediaDevices?.getUserMedia
      && typeof window.MediaRecorder !== 'undefined'
    setSupported(ok)
    if (!ok) onUnavailable?.('This browser has no microphone API — type instead.')
  }, [onUnavailable])

  const stop = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.stop()
    }
    clearInterval(timerRef.current)
  }, [])

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      chunksRef.current = []

      // Let the browser pick a container it can actually produce; Sarvam
      // accepts webm/ogg/wav among others, and Chrome/Safari disagree on
      // which they support, so this never hard-codes one.
      const preferred = ['audio/webm', 'audio/ogg', 'audio/mp4']
        .find((t) => window.MediaRecorder.isTypeSupported?.(t))
      const recorder = new window.MediaRecorder(
        stream, preferred ? { mimeType: preferred } : undefined)
      recorderRef.current = recorder

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.onstop = async () => {
        clearInterval(timerRef.current)
        setRecording(false)
        setElapsed(0)
        streamRef.current?.getTracks().forEach((t) => t.stop())

        const blob = new Blob(chunksRef.current, { type: recorder.mimeType })
        if (blob.size < 1200) return          // a stray tap, not speech
        const buf = await blob.arrayBuffer()
        let binary = ''
        const bytes = new Uint8Array(buf)
        for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
        onClip(btoa(binary), recorder.mimeType)
      }

      recorder.start()
      setRecording(true)
      setElapsed(0)
      timerRef.current = setInterval(() => {
        setElapsed((s) => {
          if (s + 1 >= MAX_SECONDS) stop()
          return s + 1
        })
      }, 1000)
    } catch (err) {
      setSupported(false)
      onUnavailable?.(
        err?.name === 'NotAllowedError'
          ? 'Microphone permission was denied — type instead.'
          : `Microphone unavailable (${err?.name || 'unknown'}) — type instead.`)
    }
  }, [onClip, onUnavailable, stop])

  useEffect(() => () => {
    clearInterval(timerRef.current)
    streamRef.current?.getTracks().forEach((t) => t.stop())
  }, [])

  if (!supported) return null

  return (
    <button
      type="button"
      className={`btn btn-ghost mic-btn${recording ? ' is-recording' : ''}`}
      onClick={recording ? stop : start}
      disabled={disabled}
      data-testid="mic-button"
      title={recording ? 'Stop and send' : 'Hold a conversation out loud'}
    >
      {recording ? (
        <>
          <span className="wave"><i /><i /><i /><i /><i /></span>
          <span className="t-num">{MAX_SECONDS - elapsed}s</span>
        </>
      ) : (
        <>
          <Icon name="mic" size={15} />
          Speak
        </>
      )}
    </button>
  )
}
