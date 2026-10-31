/*
 * One identifying colour per agent, keyed by the backend's agent key (never by display order),
 * so an agent looks the same on the dashboard columns, timeline and chat.
 * Earthy tones chosen to sit on the cream palette and stay distinguishable from each other.
 */
export const AGENT_COLOR = {
  diagnostic_expert: '#3F6690',        // slate blue
  pattern_agent: '#557A47',            // field green
  aggressive_agent: '#C26A2B',         // rust orange
  verification: '#76569A',             // plum
  ambiguity: '#B2473D',                // brick red
  human_review_coordinator: '#A27A12', // ochre
}
export const HARNESS_COLOR = '#6B6457'
export const agentColor = (key) => AGENT_COLOR[key] || HARNESS_COLOR

export const AGENT_SHORT = {
  diagnostic_expert: 'Diagnostic Expert',
  pattern_agent: 'Pattern Recognition',
  aggressive_agent: 'Rapid Triage',
  verification: 'Verification',
  ambiguity: 'Ambiguity',
  human_review_coordinator: 'Coordinator',
}
