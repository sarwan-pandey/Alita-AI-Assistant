/**
 * sovereignPalettes.js — Color palette system + emotion mapping
 *
 * PALETTES: 5 distinct color schemes with core/mid/outer RGB channels
 * EMOTION_TO_PALETTE: Maps ALITA_FACE_DATA emotional_state_label to palette id
 */

export const PALETTES = [
  {
    id: 'inferno',
    core: [255, 30, 30],       // bright red — center eye, core glow
    mid:  [255, 120, 0],       // orange — ring 1-3, lightning
    outer:[120, 0, 255],       // purple — ring 4-7, outer particles
  },
  {
    id: 'void',
    core: [0, 220, 255],       // cyan — center eye
    mid:  [0, 80, 255],        // blue — mid rings
    outer:[120, 0, 200],       // purple — outer field
  },
  {
    id: 'divine',
    core: [255, 220, 0],       // gold — center eye
    mid:  [255, 80, 0],        // amber — mid rings
    outer:[200, 0, 100],       // crimson — outer field
  },
  {
    id: 'toxic',
    core: [180, 255, 80],      // acid green — center eye
    mid:  [0, 200, 100],       // teal — mid rings
    outer:[0, 50, 180],        // deep blue — outer field
  },
  {
    id: 'omega',
    core: [255, 255, 255],     // pure white — center eye
    mid:  [180, 80, 255],      // violet — mid rings
    outer:[80, 0, 255],        // deep violet — outer field
  },
];

// Map ALITA_FACE_DATA emotional_state_label to palette id
export const EMOTION_TO_PALETTE = {
  // Supporter emotions (what Alita feels, not the user)
  'compassionate_steadiness':   'void',      // calm blue
  'warm_reassurance':           'divine',    // gold warmth
  'gentle_concern':             'void',      // cool blue
  'attentive_focus':            'omega',     // white precision
  'celebratory_joy':            'divine',    // gold celebration
  'energised_inspiration':      'inferno',   // red power
  'compassionate_anchor':       'void',      // deep blue
  'playful_warmth':             'toxic',     // acid playful
  'grounded_calm':              'void',      // blue calm
  // SER emotion fallbacks
  'neutral':   'void',
  'happy':     'divine',
  'sad':       'void',
  'angry':     'inferno',
  'fear':      'omega',
  'surprise':  'toxic',
  'disgust':   'toxic',
  // Default fallbacks by conversation_phase
  'opening':    'void',
  'building':   'void',
  'deep':       'omega',
  'resolution': 'divine',
  'closing':    'void',
};
