/**
 * AirTrack navigation. Every page here is air-operable: /track and /calibrate
 * expose their actions as big `[data-air-target]` elements, so the whole loop
 * (calibrate → control → stop) works without a keyboard.
 */

import type { Role } from './constants'

export interface NavItem {
  path: string
  label: string
  roles?: Role[]
  devOnly?: boolean
}

export const nav: NavItem[] = [
  { path: '/home', label: 'Home' },
  { path: '/track', label: 'Track' },
  { path: '/calibrate', label: 'Calibrate' },
  { path: '/settings', label: 'Settings' },
]
