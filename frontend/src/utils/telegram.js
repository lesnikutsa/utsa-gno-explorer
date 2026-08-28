import { networkProfile } from '../config/networkProfile'
import { buildConfiguredTelegramValidatorWatchUrl } from './telegramWatch'

export const TELEGRAM_BOT_USERNAME = 'UTSAGNOBot'
export const TELEGRAM_BOT_URL = `https://t.me/${TELEGRAM_BOT_USERNAME}`

export function buildTelegramValidatorWatchUrl(signingAddress) {
  return buildConfiguredTelegramValidatorWatchUrl({
    botUsername: TELEGRAM_BOT_USERNAME,
    enabled: networkProfile.telegramValidatorMonitorEnabled,
    watchPrefix: networkProfile.telegramValidatorWatchPrefix,
    signingAddress,
  })
}
