/**
 * M4 工作流自动化模块（场景引导 Wizard）公开 API
 */
export { Wizard, SceneWizardLink } from "./wizard"
export type {
  WizardProps,
  WizardStepDefinition,
  WizardStepProps,
} from "./wizard"
export {
  wizardReducer,
  canNext,
  canPrev,
  isLastStep,
  INITIAL_WIZARD_STATE,
  clampStep,
} from "./wizard-core"
export type { WizardState, WizardAction, WizardStatus } from "./wizard-core"
export {
  WIZARD_QUERY_KEYS,
  buildWizardQuery,
  parseWizardQuery,
  clampParseStep,
  hasWizardQuery,
} from "./url-sync"
export type { WizardQueryPatch } from "./url-sync"
export {
  ALL_SCENARIOS,
  ScenarioGrid,
  ScenarioCard,
  getScenarioById,
  AI_WRITING_SCENARIO,
  AI_IMAGE_SCENARIO,
  VIDEO_PIPELINE_SCENARIO,
  IMAGE_EDITOR_SCENARIO,
} from "./scenarios"
export type { ScenarioDefinition, ScenarioStepDef } from "./scenarios"
export { ScenarioGuide } from "./scenario-guide"
