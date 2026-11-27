package main

import (
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/gorilla/websocket"
	"github.com/joho/godotenv"
)

// setup main websocket handler
var upgrader = websocket.Upgrader{}

func handler(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Println(err)
		return
	}
	defer conn.Close()
	// TODO: save conn to list of clients

	// receive messages
	for {
		path := r.URL.Path // path of the request
		_, msg, err := conn.ReadMessage()
		if err != nil {
			log.Println(err)
			return
		}
		fmt.Printf("[%s] %s\n", path, msg)
	}

}

func main() {
	// get dotenv variables
	if err := godotenv.Load(); err != nil {
		log.Fatal(err)
	}

	// start background tasks
	// TODO

	// run handler
	http.HandleFunc("/", handler)
	log.Fatal(http.ListenAndServe(os.Getenv("IP")+":"+os.Getenv("PORT"), nil))
}
