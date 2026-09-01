#include <dpp/cache.h>
#include <dpp/cluster.h>
#include <dpp/discordclient.h>
#include <dpp/dispatcher.h>
#include <dpp/dpp.h>
#include <dpp/snowflake.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

bool waitForInterrupt = true;
void receivedInterrupt(int _dummyvar) { waitForInterrupt = false; }

int main(int argc, char *argv[]) {
  const char *token = getenv("DISCORD_TOKEN");
  const char *guildIDStr = getenv("TRANSCRIBE_GUILD_ID");
  dpp::snowflake guildID = strtol(guildIDStr, NULL, 10);
  const char *channelIDStr = getenv("TRANSCRIBE_CHANNEL_ID");
  dpp::snowflake channelID = strtol(channelIDStr, NULL, 10);

  // setup bot
  dpp::cluster bot(token);

  // connect to VC on bot startup
  bot.on_ready([&bot, &guildID, &channelID](const dpp::ready_t &event) {
    printf("Getting bot ready...\n");

    // join voice channel
    dpp::discord_client *client = bot.get_shard(0);
    client->connect_voice(guildID, channelID, false, false, true);
    printf("Bot has joined VC!");

    return;
  });

  // on voice receive
  bot.on_voice_receive([&](const dpp::voice_receive_t &event) {
    dpp::snowflake uid = event.user_id;
    printf("Received packet from %ld\n", (uint64_t)uid);

    return;
  });

  // run bot
  printf("Starting bot...\n");
  bot.start(dpp::st_return);

  // wait for interrupt
  signal(SIGINT, receivedInterrupt);
  while (waitForInterrupt == true)
    continue;
  printf("\n\nBeggining cleanup...\n");
  dpp::discord_client *client = bot.get_shard(0);
  client->disconnect_voice(guildID);
  bot.shutdown();
  printf("Sucessfully shutdown\n");

  return 0;
}
