/**
 * Active profile persistence.
 *
 * The profile lives in localStorage so the tracker starts instantly and keeps
 * working signed out; DeepSpace records are the durable, cross-device copy the
 * calibrator writes when the user saves. `recordId` is what lets a later save
 * update that row instead of creating a duplicate.
 */

import { useSyncExternalStore } from 'react'
import { DEFAULT_PROFILE, normalizeProfile, type CalibrationProfile } from './calibration'

const PROFILE_KEY = 'airtrack.profile.v1'
const RECORD_KEY = 'airtrack.recordId.v1'
const EVENT = 'airtrack-profile-change'

export interface ActiveProfile {
  profile: CalibrationProfile
  recordId: string | null
}

const SERVER_SNAPSHOT: ActiveProfile = { profile: DEFAULT_PROFILE, recordId: null }

let cache: ActiveProfile | null = null
const listeners = new Set<() => void>()

function read(): ActiveProfile {
  if (typeof window === 'undefined') return SERVER_SNAPSHOT
  if (cache) return cache
  try {
    const raw = window.localStorage.getItem(PROFILE_KEY)
    const recordId = window.localStorage.getItem(RECORD_KEY)
    cache = raw
      ? { profile: normalizeProfile(JSON.parse(raw)), recordId }
      : { profile: DEFAULT_PROFILE, recordId }
  } catch {
    cache = { profile: DEFAULT_PROFILE, recordId: null }
  }
  return cache
}

function notify(): void {
  for (const listener of listeners) listener()
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(EVENT))
}

export function saveActiveProfile(profile: CalibrationProfile, recordId: string | null): void {
  const normalized = normalizeProfile(profile)
  cache = { profile: normalized, recordId }
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(PROFILE_KEY, JSON.stringify(normalized))
      if (recordId) window.localStorage.setItem(RECORD_KEY, recordId)
      else window.localStorage.removeItem(RECORD_KEY)
    } catch {
      // Private mode / quota: the in-memory profile still works this session.
    }
  }
  notify()
}

/** Adopt a profile saved in DeepSpace (records are the source of truth). */
export function adoptProfile(raw: unknown, recordId: string | null): CalibrationProfile {
  const normalized = normalizeProfile(raw)
  saveActiveProfile(normalized, recordId)
  return normalized
}

export function clearActiveProfile(): void {
  cache = { profile: DEFAULT_PROFILE, recordId: null }
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.removeItem(PROFILE_KEY)
      window.localStorage.removeItem(RECORD_KEY)
    } catch {
      // ignore
    }
  }
  notify()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  if (typeof window !== 'undefined') {
    const onStorage = (event: StorageEvent) => {
      if (event.key === PROFILE_KEY || event.key === RECORD_KEY) {
        cache = null
        listener()
      }
    }
    const onEvent = () => listener()
    window.addEventListener('storage', onStorage)
    window.addEventListener(EVENT, onEvent)
    return () => {
      listeners.delete(listener)
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(EVENT, onEvent)
    }
  }
  return () => listeners.delete(listener)
}

export function useActiveProfile(): ActiveProfile {
  return useSyncExternalStore(subscribe, read, () => SERVER_SNAPSHOT)
}
