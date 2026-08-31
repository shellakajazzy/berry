package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/disgoorg/disgo"
	"github.com/disgoorg/disgo/bot"
	"github.com/disgoorg/disgo/events"
	"github.com/disgoorg/disgo/gateway"
	"github.com/disgoorg/disgo/voice"
	"github.com/disgoorg/godave/golibdave"
	"github.com/disgoorg/snowflake/v2"
)

var (
	token          = os.Getenv("DISCORD_TOKEN")
	transGuildID   = snowflake.GetEnv("TRANSCRIBE_GUILD_ID")
	transChannelID = snowflake.GetEnv("TRANSCRIBE_CHANNEL_ID")
)

func main() {
	// start bot
	client, err := disgo.New(
		token,
		bot.WithGatewayConfigOpts(
			gateway.WithIntents(
				gateway.IntentGuildVoiceStates,
			),
		),
		bot.WithEventListenerFunc(func(e *events.Ready) {
			go joinVC(e.Client())
		}),
		bot.WithVoiceManagerConfigOpts(voice.WithDaveSessionCreateFunc(golibdave.NewSession)),
	)
	if err != nil {
		panic(err)
	}
	defer client.Close(context.Background())
	if err = client.OpenGateway(context.Background()); err != nil {
		panic(err)
	}

	// wait for interrupt
	fmt.Println("Bot started, press Ctrl-C to exit")
	s := make(chan os.Signal, 1)
	signal.Notify(s, syscall.SIGINT, syscall.SIGTERM, os.Interrupt)
	<-s
}

func joinVC(client *bot.Client) {
	// setup the voice connection
	conn := client.VoiceManager.CreateConn(transGuildID)
	if conn == nil {
		fmt.Println("Could not start connection")
		return
	}

	// join the voice channel
	ctx, cancel := context.WithTimeout(context.Background(), time.Second*10)
	defer cancel()
	if err := conn.Open(ctx, transChannelID, false, false); err != nil {
		fmt.Println("Could not connect to channel")
		panic(err)
	}

	// setup receiver
	opusReceiverChannel := make(chan OpusPacket, 512)
	go OpusPacketHandler(opusReceiverChannel)
	opusReceiver := &OpusReceiver{opusReceiverChannel}
	conn.SetOpusFrameReceiver(opusReceiver)
}

// setup transcriber
type OpusPacket struct {
	userID    snowflake.ID
	timestamp int64
	opus      []byte
}
type OpusCapture struct {
	dead       bool
	processing bool
	free       bool
	userID     snowflake.ID
	timestamp  int64
	opus       []byte
}

func OpusPacketHandler(c chan OpusPacket) {
	captures := [512]*OpusCapture{}
	for i := range captures {
		captures[i] = &OpusCapture{false, false, true, 0, 0, []byte{}}
	}

	for {
		currentTimestamp := time.Now().UnixMilli()

		select {
		case opusPacket := <-c:
			if opusPacket.userID == 0 {
				continue
			}

			captureIdx := -1
			for i := range captures {
				capture := captures[i]
				if capture.userID == opusPacket.userID && currentTimestamp-capture.timestamp <= 500 {
					captureIdx = i
					break
				}
			}
			if captureIdx == -1 {
				for i := range captures {
					capture := captures[i]
					if capture.free == false {
						continue
					}

					captures[i] = &OpusCapture{false, false, false, opusPacket.userID, opusPacket.timestamp, []byte{}}
					captureIdx = i
					break
				}
			}

			capture := captures[captureIdx]
			capture.timestamp = opusPacket.timestamp
			capture.opus = append(capture.opus, opusPacket.opus...)
		default: // just don't do the above block if nothing comes through the channel
		}

		// remove dead captures
		for i := range captures {
			capture := captures[i]
			if capture.dead == false {
				continue
			}
			captures[i] = &OpusCapture{false, false, true, 0, 0, []byte{}}
		}

		// transcribe the completed captures
		for i := range captures {
			capture := captures[i]
			if capture.free == true || capture.processing == true || capture.dead == true || currentTimestamp-capture.timestamp <= 500 {
				continue
			}

			capture.processing = true
			go func() {
				fmt.Println("Finished processing capture for", capture.userID, "at index", i)
				capture.dead = true
			}()
		}
	}
}

// setup receiver for transcribing
type OpusReceiver struct{ managerChannel chan OpusPacket }

func (r *OpusReceiver) ReceiveOpusFrame(userID snowflake.ID, packet *voice.Packet) error {
	// drop failed frames
	if packet == nil || len(packet.Opus) == 0 {
		return nil
	}

	// send captured packet to the manager
	capturedPacket := OpusPacket{userID, time.Now().UnixMilli(), packet.Opus}
	r.managerChannel <- capturedPacket

	return nil
}
func (r *OpusReceiver) CleanupUser(userID snowflake.ID) {}
func (r *OpusReceiver) Close()                          {}
