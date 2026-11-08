import type { CollectionSchema } from 'deepspace/schema'
import type { CalibrationProfile } from '@/lib/airtrack/calibration'

/**
 * Saved calibration profiles, one row per profile, owned by its creator.
 *
 * This is the DeepSpace part that matters here: `useQuery` streams the rows in
 * realtime, so a second tab or a teammate's laptop sees a new profile the
 * moment it is saved. The profile itself is a JSON column — the schema keeps
 * the values queryable by name, jitter score and distance, while the tuned
 * numbers travel intact.
 */
export interface CalibrationProfileRecord {
  name: string
  profile: CalibrationProfile
  jitterScore: number
  distanceFt: number
  createdAt: string
}

export const calibrationProfilesSchema: CollectionSchema = {
  name: 'calibration_profiles',
  columns: [
    { name: 'name', storage: 'text', interpretation: 'plain', required: true, maxLength: 80 },
    { name: 'profile', storage: 'text', interpretation: { kind: 'json' }, required: true },
    { name: 'jitterScore', storage: 'number', interpretation: 'plain', default: 100 },
    { name: 'distanceFt', storage: 'number', interpretation: 'plain', default: 3 },
    { name: 'createdAt', storage: 'text', interpretation: { kind: 'datetime' } },
  ],
  // Viewer may create: a signed-out demo user (DeepSpace anonymous identity)
  // can calibrate and keep their own profiles, and can only ever see their own.
  permissions: {
    viewer: { read: 'own', create: true, update: 'own', delete: 'own' },
    member: { read: 'own', create: true, update: 'own', delete: 'own' },
    admin: { read: true, create: true, update: true, delete: true },
  },
}
