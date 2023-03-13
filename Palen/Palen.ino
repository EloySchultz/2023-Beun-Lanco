/*   Includes   */
#include <SPI.h>    
#include <FastLED.h>

// CONFIG //
#define USING_WIZNET 1; //All Seinpalen use Wiznet, so this should be defined.
#define SEINPAAL_4 1;  //Put here which seinpaal you are uploading to.
#include "devices.h"
//END OF CONFIG//



// CONSTANTS FOR ALL DEVICES //
#define LED_PACKET_BUFFER 320
unsigned int localPort = 8888;
byte gateway[] = { 192, 168, 2, 254} ;
boolean receivedPacket=false;

#if defined(USING_WIZNET)
  #include <Ethernet.h>
  #include <EthernetUdp.h>
#endif



#if defined(USING_WIZNET)
  EthernetUDP Udp;
  #define UDP_TX_PACKET_MAX_SIZE LED_PACKET_BUFFER //24 bytes by default on Atmega. Very large on ESP
#endif

char packetBuffer[LED_PACKET_BUFFER];
CRGB leds[NUM_LEDS];

/*   Functions   */

void setup() {
  Serial.begin(115200); //Somehow it is super important to have this here. Without it, ESP will go blinky on the LEDs...
FastLED.addLeds<WS2812B, DATA_PIN, GRB>(leds, NUM_LEDS);
for (int i = 0; i<NUM_LEDS; i++){
  leds[i] = CRGB::Black;
  }
delay(100);
#if defined(USING_WIZNET) || defined(USING_ENC)
  Ethernet.begin(mac, ip, gateway);
#endif
  
  Udp.begin(localPort);  
}


void showStatus() //RED = No connection, GREEN = Yes connection, BLUE = HARDWARE ERROR
  {
  for (int i = 0; i<14; i++){ 
    leds[i].r = 15 * (((Ethernet.linkStatus()==Unknown) || (Ethernet.linkStatus()==LinkOFF)) && (!(Ethernet.hardwareStatus() == EthernetNoHardware)));
    leds[i].g = 15* ((Ethernet.linkStatus()==LinkON));
    leds[i].b = 15* (Ethernet.hardwareStatus() == EthernetNoHardware);
    //Serial.println(leds[i]);
  }
  FastLED.show();
  
  delay(100);
  }
void parsePacket2(int num){
  unsigned int iled;
  for (int i = 0; i<num; i++){
    iled = ((int)packetBuffer[i*3]<<4) + (((int)packetBuffer[i*3 + 1]&0b11110000)>>4); //first 1.5 bytes are led index
    leds[iled].r = (packetBuffer[i*3 + 1]&0b00001111)<<4;                   //4th half byte
    leds[iled].g =  packetBuffer[i*3 + 2]&0b11110000;                       //5th half byte
    leds[iled].b = (packetBuffer[i*3 + 2]&0b00001111)<<4;                   //6th=last half byte
  }
}

void loop() {
  int packetSize = Udp.parsePacket();
  if (!receivedPacket)
    {
    showStatus();
    }
  if(packetSize) {
    Udp.read(packetBuffer, UDP_TX_PACKET_MAX_SIZE); //read to buffer
    parsePacket2(packetSize/3);
    receivedPacket=true;
    FastLED.show();
  }
}
