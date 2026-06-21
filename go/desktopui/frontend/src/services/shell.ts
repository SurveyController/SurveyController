import type { ShellState } from '../types'
import { GetShellState } from '../../bindings/github.com/hungrym0/SurveyController/go/desktopui/appservice'

export async function loadShellState(): Promise<ShellState> {
  return (await GetShellState()) as ShellState
}
