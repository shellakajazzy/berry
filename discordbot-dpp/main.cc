#include <dpp/cache.h>
#include <dpp/cluster.h>
#include <dpp/discordclient.h>
#include <dpp/dispatcher.h>
#include <dpp/dpp.h>
#include <dpp/snowflake.h>

#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

// Ctrl-C interrupt
bool waitForInterrupt = true;
void receivedInterrupt(int _dummyvar) { waitForInterrupt = false; }

// get current time in milliseconds
uint64_t getCurrentTimeMS(void) {
  struct timespec ts;
  clock_gettime(CLOCK_REALTIME, &ts);
  return (uint64_t)((ts.tv_sec * 1000LL) + (ts.tv_nsec * 1000000LL));
}

// transcription capture buffer
#define CAPTURES_SIZE 256
#define CAPTURES_BUF_SIZE 65536
#define TRANSCRIBE_THRESH_MS 600
typedef struct PCMCapture {
  enum PCMCaptureState {
    Free,
    Capturing,
    Transcribing,
    Dead
  } captureState = Free;
  dpp::snowflake userID = 0;
  uint64_t timestampms = 0;
  size_t captureSize = 0;
  uint8_t buf[CAPTURES_BUF_SIZE] = {};
} PCMCapture_t;
PCMCapture_t pcmCaptures[CAPTURES_SIZE];
pthread_mutex_t pcmCapturesMutex;
void *capturesManager(void *arg) {
  while (waitForInterrupt == true) {
    pthread_mutex_lock(&pcmCapturesMutex);

    for (int i = 0; i < CAPTURES_SIZE; i++) {
      PCMCapture_t capture = pcmCaptures[i];
      uint64_t timestamp = getCurrentTimeMS();

      switch (capture.captureState) {
      case PCMCapture::Dead:
        capture.captureState = PCMCapture::Free;
        capture.userID = 0;
        capture.timestampms = 0;
        capture.captureSize = 0;

        break;
      case PCMCapture::Capturing:
        if (timestamp - capture.timestampms <= TRANSCRIBE_THRESH_MS) {
          continue;
        }
        printf("Running transcription on %d\n", i);

        break;
      default:
        continue;
        break;
      }
    }

    pthread_mutex_unlock(&pcmCapturesMutex);
  }

  return NULL;
}
pthread_t capturesManagerThread;

int main(int argc, char *argv[]) {
  // get environment variables
  const char *token = getenv("DISCORD_TOKEN");
  const char *guildIDStr = getenv("TRANSCRIBE_GUILD_ID");
  dpp::snowflake guildID = strtol(guildIDStr, NULL, 10);
  const char *channelIDStr = getenv("TRANSCRIBE_CHANNEL_ID");
  dpp::snowflake channelID = strtol(channelIDStr, NULL, 10);

  // setup bot
  dpp::cluster bot(token);

  // connect to VC on bot startup
  bot.on_ready([&bot, &guildID, &channelID](const dpp::ready_t &event) {
    printf("Getting bot ready, do not exit...\n");

    // join voice channel
    pthread_create(&capturesManagerThread, NULL, capturesManager, NULL);
    dpp::discord_client *client = bot.get_shard(0);
    client->connect_voice(guildID, channelID, false, false, true);

    return;
  });
  bot.on_voice_ready([&bot](const dpp::voice_ready_t &event) {
    printf("Bot has joined VC, press Ctrl-C to exit\n");
    return;
  });

  // on voice receive
  bot.on_voice_receive([&](const dpp::voice_receive_t &event) {
    // get variables
    dpp::snowflake uid = event.user_id;
    if (uid <= 0) {
      return;
    }
    uint8_t *audio = (uint8_t *)event.audio;
    size_t audio_size = event.audio_size;
    if (audio_size <= 0) {
      return;
    }
    uint64_t timestamp = getCurrentTimeMS();

    // write received audio to capture buffers
    pthread_mutex_lock(&pcmCapturesMutex);

    // check if there is a preexisting capture that is usable
    int captureIdx = -1;
    for (int i = 0; i < CAPTURES_SIZE; i++) {
      PCMCapture_t capture = pcmCaptures[i];
      if (capture.captureState != PCMCapture::Capturing ||
          capture.userID != uid ||
          timestamp - capture.timestampms > TRANSCRIBE_THRESH_MS) {
        continue;
      }

      captureIdx = i;
      break;
    }
    if (captureIdx <= -1) {
      // look for the first available capture to write to
      for (int i = 0; i < CAPTURES_SIZE; i++) {
        PCMCapture_t capture = pcmCaptures[i];
        if (capture.captureState != PCMCapture::Free) {
          continue;
        }

        capture.captureState = PCMCapture::Capturing;
        capture.userID = uid;

        captureIdx = i;
        break;
      }
    }

    // save capture
    PCMCapture_t capture = pcmCaptures[captureIdx];
    capture.timestampms = timestamp;
    for (int i = 0; i < audio_size; i++) {
      capture.buf[capture.captureSize] = audio[i];
      capture.captureSize = capture.captureSize + 1;
    }
    printf("Saved capture to index %d\n", captureIdx);

    // free the lock on the pcmCapture
    pthread_mutex_unlock(&pcmCapturesMutex);

    return;
  });

  // run bot
  printf("Starting bot...\n");
  bot.start(dpp::st_return);

  // wait for interrupt
  signal(SIGINT, receivedInterrupt);
  while (waitForInterrupt == true) {
    continue;
  }

  // cleanup bot
  printf("\n\nBeggining cleanup...\n");
  dpp::discord_client *client = bot.get_shard(0);
  client->disconnect_voice(guildID);
  bot.shutdown();
  pthread_join(capturesManagerThread, NULL);
  printf("Sucessfully shutdown\n");

  return 0;
}
