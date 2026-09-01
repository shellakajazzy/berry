package main

import (
	"context"
	"encoding/binary"
	"encoding/json"
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

	vosk "github.com/alphacep/vosk-api/go"
	"gopkg.in/hraban/opus.v2"
)

var (
	token          = os.Getenv("DISCORD_TOKEN")
	transGuildID   = snowflake.GetEnv("TRANSCRIBE_GUILD_ID")
	transChannelID = snowflake.GetEnv("TRANSCRIBE_CHANNEL_ID")
	voskModelPath  = os.Getenv("VOSK_MODEL_PATH")
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
	fmt.Println("Joining VC, please wait...")

	// create the Vosk transcriber
	fmt.Println("Loading Vosk model...")
	voskModel, err := vosk.NewModel(voskModelPath)
	if err != nil {
		fmt.Println("Could not load vosk model")
		panic(err)
	}

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
	go OpusPacketHandler(opusReceiverChannel, voskModel)
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
	opus       [][]byte
}

func OpusPacketHandler(c chan OpusPacket, voskModel *vosk.VoskModel) {
	captures := [512]*OpusCapture{}
	for i := range captures {
		captures[i] = &OpusCapture{false, false, true, 0, 0, [][]byte{}}
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

					captures[i] = &OpusCapture{false, false, false, opusPacket.userID, opusPacket.timestamp, [][]byte{}}
					captureIdx = i
					break
				}
			}

			capture := captures[captureIdx]
			capture.timestamp = opusPacket.timestamp
			capture.opus = append(capture.opus, opusPacket.opus)
		default: // just don't do the above block if nothing comes through the channel
		}

		// remove dead captures
		for i := range captures {
			capture := captures[i]
			if capture.dead == false {
				continue
			}
			captures[i] = &OpusCapture{false, false, true, 0, 0, [][]byte{}}
		}

		// transcribe the completed captures
		for i := range captures {
			capture := captures[i]
			if capture.free == true || capture.processing == true || capture.dead == true || currentTimestamp-capture.timestamp <= 500 {
				continue
			}

			capture.processing = true
			go func() {
				// mark capture as being processes

				// setup the recognizer
				rec, err := vosk.NewRecognizer(voskModel, 16000.0)
				if err != nil {
					fmt.Println("Could not start Vosk transcriber")
					panic(err)
				}

				// convert the raw opus into 1 channel, 16000 kHz pcm
				decoder, err := opus.NewDecoder(16000, 1)
				if err != nil {
					fmt.Println("Could not create audio decoder")
					panic(err)
				}
				for _, packet := range capture.opus {
					frame := make([]int16, 1920)
					n, err := decoder.Decode(packet, frame)
					if err != nil {
						fmt.Println("Error decoding audio")
						fmt.Println("error:", err)
						return
					}

					pcmBytes := make([]byte, n*2)
					for i := range n {
						pcmFrame := make([]byte, 2)
						binary.LittleEndian.PutUint16(pcmFrame, uint16(frame[i]))
						pcmBytes = append(pcmBytes, pcmFrame...)
					}

					rec.AcceptWaveform(pcmBytes)
				}

				// do the transcription
				fmt.Println("Getting transcription in index", i)
				var result map[string]interface{}
				json.Unmarshal([]byte(rec.FinalResult()), result)
				fmt.Println(capture.userID, ":", result)

				// mark capture for reuse
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
