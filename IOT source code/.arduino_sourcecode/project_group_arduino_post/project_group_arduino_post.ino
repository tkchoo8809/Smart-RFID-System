#include <WiFiNINA.h>
#include <SPI.h>
#include <MFRC522.h>
#include <string.h>
#include <stdlib.h>
#include <EEPROM.h>

#define ADDR_MODE 0
#define ADDR_LOC_START 1
#define MAX_LOC_LENGTH 32

#define MAX_LEN 16

#define SAD 10
#define RST 9

// ---------- Status LEDs ----------
#define LED_RED    2
#define LED_YELLOW 3
#define LED_GREEN  5

void ledsOff() {
  digitalWrite(LED_RED, LOW);
  digitalWrite(LED_YELLOW, LOW);
  digitalWrite(LED_GREEN, LOW);
}

void ledBusy() {         // yellow ON
  ledsOff();
  digitalWrite(LED_YELLOW, HIGH);
}

void ledSuccess() {      // green ON
  ledsOff();
  digitalWrite(LED_GREEN, HIGH);
}

void ledFail() {         // red ON
  ledsOff();
  digitalWrite(LED_RED, HIGH);
}

MFRC522 nfc(SAD, RST);

// WiFi creds
// char ssid[] = "SINGTEL-5410"; 
// char pass[] = "MqcgbHcsjdY3";
// char ssid[] = "TheBest"; 
// char pass[] = "udanayeo";
char ssid[] = "TK"; 
char pass[] = "Chaosit3009.";  
int status = WL_IDLE_STATUS;

// HTTP server
WiFiServer server(80);

enum Mode { MODE_READ, MODE_WRITE };
Mode currentMode = MODE_WRITE;   // default start in WRITE mode

// Buffer for the next tag write
String pendingCat = "";
String pendingLocation = "";
String pendingTs = "";   // format: YYMMDDHHMMSS

// Buffer timing (wait a bit after receiving HTTP before writing)
unsigned long lastBufferedMs = 0;
const unsigned long BUFFER_READY_DELAY = 800; // ms

unsigned long lastTagActionMs = 0;
const unsigned long TAG_COOLDOWN_MS = 1200;  // 1.2s

bool isPythonDataValid = true;
String currentLocation = "UNKNOWN";

// Google Sheet
String DEPLOYMENT_ID = "AKfycbzJuX7P3OQ25ZBMqRZwnyI56U78QSnx3IW13OY7W2T9jaTQ2Wa2pJZ2JSrDXJ5pCdmR";
String serialBuffer = "";

String uidToString(const byte serial[5]) {
  String s = "";
  // Use only first 4 bytes (ignore the 5th BCC byte)
  for (int i = 0; i < 4; i++) {
    if (serial[i] < 0x10) s += "0";
    s += String(serial[i], HEX);
  }
  s.toUpperCase();
  return s;
}

String urlEncode(const String &str) {
  String out = "";
  for (unsigned int i = 0; i < str.length(); i++) {
    char c = str[i];
    if (isalnum(c) || c == '-' || c == '_' || c == '.' ) out += c;
    else if (c == ' ') out += "%20";
    else {
      char buf[4];
      sprintf(buf, "%%%02X", (unsigned char)c);
      out += buf;
    }
  }
  return out;
}

bool logToDashboard = true;

void logLine(String msg) {
  Serial.println(msg);   // always print to Serial Monitor

  if (logToDashboard) {  // only store if allowed
    serialBuffer += msg + "\n";

    if (serialBuffer.length() > 1500) {
      serialBuffer = serialBuffer.substring(serialBuffer.length() - 1000);
    }
  }
}

void dashLine(const String &msg) {
  // Always store to dashboard, no matter what
  Serial.println(msg);           // optional: still show on Serial Monitor
  serialBuffer += msg + "\n";

  if (serialBuffer.length() > 1500) {
    serialBuffer = serialBuffer.substring(serialBuffer.length() - 1000);
  }
}

static int readLine(WiFiSSLClient &c, char *buf, int maxLen, unsigned long timeoutMs) {
  int idx = 0;
  unsigned long start = millis();
  while (millis() - start < timeoutMs) {
    while (c.available()) {
      char ch = c.read();
      if (ch == '\r') continue;
      if (ch == '\n') { buf[idx] = '\0'; return idx; }
      if (idx < maxLen - 1) buf[idx++] = ch;
    }
    if (!c.connected()) break;
  }
  buf[idx] = '\0';
  return idx;
}

static bool startsWith(const char *s, const char *prefix) {
  return strncmp(s, prefix, strlen(prefix)) == 0;
}

static void readPlainBody(WiFiSSLClient &c, char *out, int outMax) {
  out[0] = '\0';
  int idx = 0;
  unsigned long start = millis();
  while (millis() - start < 5000 && idx < outMax - 1) {
    while (c.available() && idx < outMax - 1) {
      char ch = c.read();
      if (ch == '\r') continue;
      out[idx++] = ch;
    }
    if (!c.connected()) break;
  }
  out[idx] = '\0';
}

static void readChunkedBody(WiFiSSLClient &c, char *out, int outMax) {
  out[0] = '\0';
  int outIdx = 0;
  char line[32];

  while (true) {
    int len = readLine(c, line, sizeof(line), 5000);
    if (len <= 0) break;

    int chunkSize = (int)strtol(line, NULL, 16);
    if (chunkSize <= 0) break;

    while (chunkSize > 0 && outIdx < outMax - 1) {
      if (!c.available()) { if (!c.connected()) break; continue; }
      out[outIdx++] = c.read();
      chunkSize--;
    }
    while (chunkSize > 0) {
      if (c.available()) { c.read(); chunkSize--; }
      else if (!c.connected()) break;
    }

    // consume trailing LF after chunk
    unsigned long start = millis();
    while (millis() - start < 1000) {
      if (c.available()) { if (c.read() == '\n') break; }
      else if (!c.connected()) break;
    }
  }

  out[outIdx] = '\0';
}

// Connect + GET, follow redirect if 302/303/307/308
String sendToGoogleSheet(const String &pathOnScriptGoogle) {
  // pathOnScriptGoogle should be like:
  // "/macros/s/<DEPLOYMENT_ID>/exec?op=register&tag_id=...&item_id=...&cat=..."

  String currentUrl = pathOnScriptGoogle;

  for (int hop = 0; hop < 2; hop++) {  // allow 1 redirect
    WiFiSSLClient client;
    client.setTimeout(8000);

    // Default host/path
    String host = "script.google.com";
    String path = currentUrl;

    // If currentUrl is a full https URL, split host/path
    if (currentUrl.startsWith("https://")) {
      int hs = 8;
      int ps = currentUrl.indexOf('/', hs);
      host = (ps >= 0) ? currentUrl.substring(hs, ps) : currentUrl.substring(hs);
      path = (ps >= 0) ? currentUrl.substring(ps) : "/";
    }

    // Optional: reconnect WiFi if dropped
    if (WiFi.status() != WL_CONNECTED) {
      status = WiFi.begin(ssid, pass);
      delay(1500);
    }

    // connect retry
    bool ok = false;
    for (int attempt = 0; attempt < 3; attempt++) {
      if (client.connect(host.c_str(), 443)) { ok = true; break; }
      delay(400);
    }
    if (!ok) {
      logLine(F("Sheets connect failed"));
      client.stop();
      return "";
    }

    // Send request
    client.print(F("GET "));
    client.print(path);
    client.println(F(" HTTP/1.1"));
    client.print(F("Host: "));
    client.println(host);
    client.println(F("Connection: close"));
    client.println();

    // --- Read status line ---
    char line[700];
    readLine(client, line, sizeof(line), 5000);

    // --- Read headers ---
    bool isChunked = false;
    String location = "";

    while (true) {
      int n = readLine(client, line, sizeof(line), 5000);
      if (n <= 0) break;
      if (line[0] == '\0') break; // blank line = end headers

      if (startsWith(line, "Location:")) {
        // store redirect target
        location = String(line + 9);
        location.trim();
      } else if (startsWith(line, "Transfer-Encoding:")) {
        // detect chunked
        if (strstr(line, "chunked") != nullptr) isChunked = true;
      }
    }

    // If redirect, follow it (no caching)
    if (location.length() > 0) {
      Serial.println(F("Following redirect..."));
      Serial.println(location);
      client.stop();
      currentUrl = location;
      delay(400);
      continue;
    }

    // --- Read body (small) ---
    char body[160];
    if (isChunked) readChunkedBody(client, body, sizeof(body));
    else           readPlainBody(client, body, sizeof(body));

    client.stop();

    String out = String(body);
    out.trim();
    return out;
  }

  return "";
}

// ---------- Handle Mode Switch ---------
void handleModeSwitch() {
  if (!Serial.available()) return;
  char c = Serial.read();

  bool modeChanged = false;

  if (c == 'r' || c == 'R') {
    currentMode = MODE_READ;
    Serial.println("MODE = READ");
    modeChanged = true;
  } 
    else if (c == 'w' || c == 'W') {
    currentMode = MODE_WRITE;
    Serial.println("MODE = WRITE");
    modeChanged = true;
  }
  if (modeChanged) {
    // Save both the new mode and the existing location to EEPROM
    saveSettingsToEEPROM(currentMode, currentLocation);
    
    resetRFID();
    // Small delay to allow EEPROM commit to stabilize 
    // and RFID to settle
    delay(100);
  }
}


// --------- Read Mode ------------
bool readBlock(byte blockAddr, byte out[16], const byte serial[5]) {
  if (!authBlock(blockAddr, serial)) return false;

  byte result = nfc.readFromTag(blockAddr, out);
  logLine("read block " + String(blockAddr) + " result: " + String(result));

  return (result == MI_OK);
}

// String readTag_simple(const byte serial[5]) {
//   byte b8[16], b9[16]; //b10[16]

//   if (!readBlock(8, b8, serial)) { Serial.println("Read block 8 failed"); return; }
//   if (!readBlock(9, b9, serial)) { Serial.println("Read block 9 failed"); return; }
//   // if (!readBlock(10, b10, serial)) { Serial.println("Read block 10 failed"); return; }

//   // make safe C-strings (16 bytes + null)
//   char s8[17], s9[17]; //, s10[17];
//   memcpy(s8, b8, 16); s8[16] = '\0';
//   memcpy(s9, b9, 16); s9[16] = '\0';
//   // memcpy(s10, b10, 16); s10[16] = '\0';

//   String tagId = uidToString(serial);

//   logLine("TAG ID: " + tagId);
//   logLine(String(s8));   // CAT:...
//   logLine(String(s9));   // TS:... location no longer needed
//   // logLine(String(s10));  // TS:...
  
//   return tagId;
// }
String readTag_simple(const byte serial[5]) {
  byte b8[16], b9[16];

  if (!readBlock(8, b8, serial)) return ""; 
  if (!readBlock(9, b9, serial)) return ""; 

  char s8[17], s9[17];
  memcpy(s8, b8, 16); s8[16] = '\0';
  memcpy(s9, b9, 16); s9[16] = '\0';

  String tagId = uidToString(serial);
  String catData = String(s8);
  String tsData = String(s9);

  // Clean the prefixes so Google Sheets gets pure data
  if (catData.startsWith("CAT:")) catData = catData.substring(4);
  // if (tsData.startsWith("TS:"))   tsData = tsData.substring(3);

  logLine("TAG ID: " + tagId);
  logLine("CAT: " + catData);
  // logLine("TS: " + tsData);
  
  return tagId + "|" + catData;
}
// ---------- WiFi helpers ----------
void enable_WiFi() {
  if (WiFi.status() == WL_NO_MODULE) {
    Serial.println("Communication with WiFi module failed!");
    while (true);
  }
}

void connect_WiFi() {
  while (status != WL_CONNECTED) {
    // logLine("Connecting to SSID: ");
    // logLine(ssid);
    status = WiFi.begin(ssid, pass);
    delay(2000);
  }
}

void printWifiStatus() {
  Serial.print("SSID: ");
  Serial.println(WiFi.SSID());

  IPAddress ip = WiFi.localIP();
  String ipStr = String(ip[0]) + "." + String(ip[1]) + "." + String(ip[2]) + "." + String(ip[3]);
  logLine("UNO IP Address: " + ipStr);

  long rssi = WiFi.RSSI();
  Serial.print("Signal (RSSI): ");
  Serial.print(rssi);
  Serial.println(" dBm");
}

// ---------- URL parsing ----------
String getParam(const String& qs, const String& key) {
  String k = key + "=";
  int start = qs.indexOf(k);
  if (start == -1) return "";
  start += k.length();
  int end = qs.indexOf('&', start);
  if (end == -1) end = qs.length();

  String val = qs.substring(start, end);

  val.replace("+", " ");     // ✅ ADD THIS LINE
  val.replace("%20", " ");

  return val;
}

// Receive from Python: /setItem?item_id=1234567&cat=bottle
void handleHttp() {
  WiFiClient client = server.available();
  if (!client) return;

  // Read request line
  String reqLine = client.readStringUntil('\r');
  if (reqLine.startsWith("GET /")) { 
    client.readStringUntil('\n');
  }
  // Read and discard the rest of the HTTP headers until blank line
  while (client.connected()) {
    String line = client.readStringUntil('\n');
    if (line == "\r" || line.length() == 0) break;
  }

  // if (reqLine.startsWith("GET /setItem?")) {
  //   // ✅ Only allow buffering in WRITE mode
  //   if (currentMode != MODE_WRITE) {
  //     client.println("HTTP/1.1 409 Conflict");
  //     client.println("Content-Type: text/plain");
  //     client.println("Connection: close");
  //     client.println();
  //     client.println("Not in WRITE mode");
  //     delay(20);
  //     client.stop();
  //     return;
  //   }

  //   String qs = reqLine.substring(String("GET /setItem?").length());
  //   int sp = qs.indexOf(' ');
  //   if (sp != -1) qs = qs.substring(0, sp);
  //   Serial.println("This is QS:" + qs);


  //   String cat = getParam(qs, "cat");
  //   String location = getParam(qs, "location");
  //   String ts = getParam(qs, "ts");  // YYMMDDHHMMSS
  //   String statusStr = getParam(qs, "status");
  //   statusStr.trim(); // <-- NEW: Removes hidden spaces or newlines
  //   statusStr.toLowerCase(); // <-- NEW: Forces it to lowercase just in cas
  //   if (cat.length() && location.length() && ts.length()) {
  //     pendingCat = cat;
  //     pendingLocation = location;
  //     pendingTs = ts;
  //     lastBufferedMs = millis();
  //     Serial.println("before" + statusStr);

  //     if (statusStr == "valid") {
  //         isPythonDataValid = true;
  //     } else {
  //         isPythonDataValid = false;
  //     }
  //     Serial.println("after" + statusStr);

  //     logLine("Buffered: " + pendingCat + " / " + pendingLocation + " / " + pendingTs);

  //     client.println("HTTP/1.1 200 OK");
  //     client.println("Content-Type: text/plain");
  //     client.println("Connection: close");
  //     client.println();
  //     client.println("OK");
  //   } else {
  //     client.println("HTTP/1.1 400 Bad Request");
  //     client.println("Content-Type: text/plain");
  //     client.println("Connection: close");
  //     client.println();

  //     if (!cat.length()) client.println("Missing cat");
  //     else if (!location.length()) client.println("Missing location");
  //     else client.println("Missing ts");
  //   }
  // }
  if (reqLine.startsWith("POST /setItem")) {
      // 1. Check Mode
      if (currentMode != MODE_WRITE) {
          client.println("HTTP/1.1 409 Conflict\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nNot in WRITE mode");
          delay(20);
          client.stop();
          return;
      }

      // 2. Read Headers to find Content-Length
      int contentLength = 0;
      while (client.connected()) {
          String line = client.readStringUntil('\n');
          if (line == "\r") break; // Blank line signifies end of headers
          if (line.startsWith("Content-Length: ")) {
              contentLength = line.substring(16).toInt();
          }
      }

      // 3. Read the Body (the actual data)
      String body = "";
      for (int i = 0; i < contentLength; i++) {
          if (client.available()) {
              body += (char)client.read();
          }
      }

      // Now 'body' contains "cat=xyz&location=abc&ts=123&status=valid"
      Serial.println("Received Body: " + body);

      // 4. Parse using your existing getParam function
      String cat = getParam(body, "cat");
      String location = getParam(body, "location");
      String ts = getParam(body, "ts");
      String statusStr = getParam(body, "status");
      
      statusStr.trim();
      statusStr.toLowerCase();

      if (cat.length() && location.length() && ts.length()) {
          pendingCat = cat;
          pendingLocation = location;
          pendingTs = ts;
          lastBufferedMs = millis();
          isPythonDataValid = (statusStr == "valid");

          logLine("Buffered: " + pendingCat + " / " + pendingLocation + " / " + pendingTs);

          client.println("HTTP/1.1 200 OK");
          client.println("Content-Type: text/plain");
          client.println("Connection: close");
          client.println();
          client.println("OK");
      } else {
          client.println("HTTP/1.1 400 Bad Request\r\n\r\nMissing Params");
      }
  }
  // else if (reqLine.startsWith("GET /mode?")) {
  //   String qs = reqLine.substring(String("GET /mode?").length());
  //   int sp = qs.indexOf(' ');
  //   if (sp != -1) qs = qs.substring(0, sp);

  //   String m = getParam(qs, "m");  // expects r / w / e
  //   m.toLowerCase();

  //   if (m == "r") {
  //     currentMode = MODE_READ;
  //     logLine("MODE = READ (from dashboard)");
  //     resetRFID();
  //   } else if (m == "w") {
  //     currentMode = MODE_WRITE;
  //     logLine("MODE = WRITE (from dashboard)");
  //     resetRFID();
  //   } else {
  //     client.println("HTTP/1.1 400 Bad Request");
  //     client.println("Content-Type: text/plain");
  //     client.println("Connection: close");
  //     client.println();
  //     client.println("Invalid mode. Use m=r|w");
  //     delay(200);
  //     client.stop();
  //     return;
  //   }

  //   client.println("HTTP/1.1 200 OK");
  //   client.println("Content-Type: text/plain");
  //   client.println("Connection: close");
  //   client.println();
  //   client.print("OK MODE=");
  //   client.println(m);
  // }
  else if (reqLine.startsWith("POST /mode")) {
    Serial.println(reqLine);
    // 1. Skip all HTTP headers until the blank line (\r)
    // This "drains" the buffer so we can reach the body
    while (client.connected()) {
      String line = client.readStringUntil('\n');
      if (line == "\r") break; 
    }

    // 2. Read the body (m=w)
    // Note: We use readString() to capture the payload after the headers
    String body = client.readString();
    Serial.println("Final Body: " + body);

    // 3. Parse using your existing getParam helper
    String mVal = "";
    String locVal = "";
    // Find the positions of the keys
    int mPos = body.indexOf("m=");
    int locPos = body.indexOf("loc=");

    // Extract Mode (usually first)
    if (mPos != -1) {
      int endM = body.indexOf('&', mPos);
      if (endM == -1) endM = body.length();
      mVal = body.substring(mPos + 2, endM);
    }
    Serial.println(mVal);
    // Extract Location
    if (locPos != -1) {
      int endLoc = body.indexOf('&', locPos);
      if (endLoc == -1) endLoc = body.length();
      locVal = body.substring(locPos + 4, endLoc);
    }
    Serial.println(locVal);
    bool success = false;
    if (mVal == "r") {
      currentMode = MODE_READ;
      logLine("MODE = READ (from dashboard)");
      success = true;
    } else if (mVal == "w") {
      currentMode = MODE_WRITE;
      logLine("MODE = WRITE (from dashboard)");
      success = true;
    }
    
    if (locVal != "") {
      currentLocation = urlDecode(locVal); // Update your global location variable
      logLine("LOCATION = " + urlDecode(locVal) + " (from dashboard)");
      success = true;
    }
    
    if (!success) {
      client.println("HTTP/1.1 400 Bad Request");
      client.println("Content-Type: text/plain");
      client.println("Connection: close");
      client.println();
      client.println("Invalid parameters. Use m=r/w, loc=string");
      delay(200);
      client.stop();
      return;
    }
    if (success) {
      saveSettingsToEEPROM((int)currentMode, currentLocation);
      lastBufferedMs = millis(); // Reset buffer timer if applicable
      
      resetRFID();
      client.println("HTTP/1.1 200 OK");
      client.println("Content-Type: text/plain");
      client.println("Connection: close");
      client.println();
      client.print("OK MODE="); client.println(mVal);
      client.print(" LOC="); client.println(mVal);
    }
  }
  else if (reqLine.startsWith("GET /status")) {
    String modeStr = "UNKNOWN";
    if (currentMode == MODE_READ) modeStr = "READ";
    else if (currentMode == MODE_WRITE) modeStr = "WRITE";

    client.println("HTTP/1.1 200 OK");
    client.println("Content-Type: text/plain");
    client.println("Connection: close");
    client.println();
    client.print("MODE=");
    client.println(modeStr);
  }
  else if (reqLine.startsWith("POST /logs")) {
      bool doClear = false;

      // 1. Read headers to find Content-Length
      int contentLength = 0;
      while (client.connected()) {
          String line = client.readStringUntil('\n');
          if (line == "\r") break; // End of headers
          if (line.startsWith("Content-Length: ")) {
              contentLength = line.substring(16).toInt();
          }
      }

      // 2. Read the Body
      String body = "";
      for (int i = 0; i < contentLength; i++) {
          if (client.available()) {
              body += (char)client.read();
          }
      }

      // 3. Check for the clear parameter in the body
      // Expecting body like: clear=1
      String c = getParam(body, "clear");
      doClear = (c == "1");

      // 4. Response
      client.println("HTTP/1.1 200 OK");
      client.println("Content-Type: text/plain");
      client.println("Connection: close");
      client.println();
      
      // Send the logs back before we wipe them
      client.print(serialBuffer);

      // 5. Cleanup
      if (doClear) {
          serialBuffer = "";
          // Serial.println("Logs cleared via POST");
      }
  }
  else if (reqLine.startsWith("GET /logs")) {

    // parse query string (optional)
    // bool doClear = false;
    // int qmark = reqLine.indexOf('?');
    // if (qmark != -1) {
    //   String qs = reqLine.substring(qmark + 1);
    //   int sp = qs.indexOf(' ');
    //   if (sp != -1) qs = qs.substring(0, sp);

    //   String c = getParam(qs, "clear");   // /logs?clear=1
    //   doClear = (c == "1");
    // }

    client.println("HTTP/1.1 200 OK");
    client.println("Content-Type: text/plain");
    client.println("Connection: close");
    client.println();
    client.print(serialBuffer);

    // if (doClear) serialBuffer = "";   // ✅ clear only when asked
  }
  
  // Give time for data to flush before closing
  delay(200);
  ledsOff();
  client.stop();
}

// ---------- RFID write helpers ----------
void pad16(byte out[16], const String& s) {
  for (int i = 0; i < 16; i++) out[i] = 0x00;
  int n = s.length();
  if (n > 16) n = 16;
  for (int i = 0; i < n; i++) out[i] = (byte)s[i];
}

bool authBlock(byte blockAddr, const byte serial[5]) {
  // Default key A = FF FF FF FF FF FF
  byte keyA[6] = {0xFF,0xFF,0xFF,0xFF,0xFF,0xFF};

  // Many libs use: authenticate(byte authMode, byte blockAddr, byte* key, byte* uid)
  // authMode is often MF1_AUTHENT1A (Key A)
  byte res = nfc.authenticate(MF1_AUTHENT1A, blockAddr, keyA, (byte*)serial);

  logLine("auth block " + String(blockAddr) + " result: " + String(res));


  return (res == MI_OK);
}

bool writeBlock(byte blockAddr, const String& text16, const byte serial[5]) {
  if (!authBlock(blockAddr, serial)) return false;

  byte data16[16];
  pad16(data16, text16);

  byte result = nfc.writeToTag(blockAddr, data16);

  logLine("write block " + String(blockAddr) + " result: " + String(result));

  return (result == MI_OK);
}


bool writeToTag_simple(const String& cat, const String& ts, const byte serial[5]) {
  // Block 8: Category (No prefix, leaves full 16 chars for the name)
  if (!writeBlock(8, cat, serial)) return false;

  // Block 9: Timestamp 
  if (!writeBlock(9, ts, serial)) return false;

  return true;
}

// Set LEDs
bool setLED(String request) {
  if (request.indexOf("GET /red") >= 0) {
    digitalWrite(LED_RED, HIGH);
    digitalWrite(LED_GREEN, LOW);
    return true;
  } 
  else if (request.indexOf("GET /green") >= 0) {
    digitalWrite(LED_RED, LOW);
    digitalWrite(LED_GREEN, HIGH);
    return true;
  }
  return false; 
}

void setup() {
  Serial.begin(9600);
  while (!Serial);

  pinMode(LED_RED, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  ledsOff();
  enable_WiFi();
  connect_WiFi();
  printWifiStatus();

  server.begin();
  Serial.println("HTTP server started on port 80");

  SPI.begin();

  Serial.println("Looking for MFRC522...");
  nfc.begin();

  byte version = nfc.getFirmwareVersion();
  if (!version) {
    Serial.println("Didn't find MFRC522 board.");
    while (1);
  }
  logLine("Found chip MFRC522, Firmware 0x");
  Serial.println(version, HEX);

  currentMode = (Mode)readModeFromEEPROM(); // Cast int back to Enum
  String savedLoc = readLocationFromEEPROM();
  if (savedLoc == "" || savedLoc == "255" || savedLoc == "DEFAULT") {
      currentLocation = "DEFAULT";
  } else {
      currentLocation = savedLoc;
  }
  logLine("Booted in:");
  logLine("Mode: " + String(currentMode == MODE_WRITE ? "WRITE" : "READ"));
  logLine("Location: " + currentLocation);
}

void waitForTagRemoval() {
  byte tmp[MAX_LEN];
  int clearCount = 0;

  delay(250); // debounce

  unsigned long start = millis();
  const unsigned long TIMEOUT_MS = 5000;

  while (clearCount < 5) {
    // timeout safety
    if (millis() - start > TIMEOUT_MS) {
      Serial.println("Removal timeout. Continuing anyway.");
      break;
    }
    
    byte s = nfc.requestTag(MF1_REQIDL, tmp);
    if (s != MI_OK) clearCount++;
    else clearCount = 0;

    delay(80);
  }

  lastTagActionMs = 0;
  logLine("Tag removed (or timeout). Ready.");
}

void resetRFID() {
  // Re-init the RC522 to clear any stuck state
  nfc.begin();
  delay(50);
}

// Save to persistent storage
void saveSettingsToEEPROM(int mode, String loc) {
  // 1. Save Mode (as a single byte)
  EEPROM.write(ADDR_MODE, (byte)mode);

  // 2. Save Location String
  // We start writing from ADDR_LOC_START
  int len = loc.length();
  if (len > MAX_LOC_LENGTH - 1) len = MAX_LOC_LENGTH - 1; // Cap length

  for (int i = 0; i < len; i++) {
    EEPROM.write(ADDR_LOC_START + i, loc[i]);
  }
  EEPROM.write(ADDR_LOC_START + len, '\0'); // Crucial: Null terminator

  // 3. Commit to Flash (Required for ESP8266/ESP32)
  logLine("Settings saved to EEPROM. Mode: "+ String(mode) + "| Loc: " + loc);
}

// --- READ MODE ---
int readModeFromEEPROM() {
  byte mode = EEPROM.read(ADDR_MODE);
  // If memory is fresh (255), default to READ mode (0)
  if (mode == 255) return 0; 
  return (int)mode;
}

// --- READ LOCATION ---
String readLocationFromEEPROM() {
  String loc = "";
  for (int i = 0; i < MAX_LOC_LENGTH; i++) {
    char c = EEPROM.read(ADDR_LOC_START + i);
    
    // Stop if we hit the terminator or empty memory
    if (c == '\0' || (byte)c == 255) break;
    loc += c;
  }
  // Decode here to handle any legacy '+' or '%20'
  return urlDecode(loc);
}

String urlDecode(String str) {
    String decoded = "";
    char c;
    char code0;
    char code1;

    for (int i = 0; i < str.length(); i++) {
        c = str.charAt(i);

        if (c == '+') {
            // Replace '+' with a space
            decoded += ' ';
        } else if (c == '%' && i + 2 < str.length()) {
            // Handle percent encoding (e.g., %20)
            code0 = str.charAt(++i);
            code1 = str.charAt(++i);
            
            // Convert hex to decimal
            decoded += (char)(valueFromHex(code0) << 4 | valueFromHex(code1));
        } else {
            decoded += c;
        }
    }
    return decoded;
}

// Helper function to convert Hex character to integer
byte valueFromHex(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return 0;
}

void loop() {
  handleModeSwitch();
  handleHttp();  // ✅ always listen for /mode and /setItem

  logToDashboard = true;

  // ========= RFID scan (runs in ALL modes) =========
  byte status;
  byte data[MAX_LEN];
  byte serial[5];

  // Prevent hammering the reader too fast
  if (millis() - lastTagActionMs < TAG_COOLDOWN_MS) return;

  status = nfc.requestTag(MF1_REQIDL, data);
  // Serial.println(status);
  if (status != MI_OK) return;

  lastTagActionMs = millis();

  Serial.print("Type bytes: ");
  Serial.print(data[0], HEX);
  Serial.print(" ");
  Serial.println(data[1], HEX);

  bool gotUID = false;
  for (int tries = 0; tries < 8; tries++) {
    status = nfc.antiCollision(data);
    if (status == MI_OK) { gotUID = true; break; }
    delay(50);
  }

  if (!gotUID) {
    Serial.println("Anti-collision failed");
    resetRFID();
    delay(200);
    return;
  }

  memcpy(serial, data, 5);
  nfc.selectTag(serial);

  // ========= MODE: READ =========
  if (currentMode == MODE_READ) {
    logLine("Tag detected -> READ mode");

    // (At this point currentMode must be MODE_READ)
    dashLine("Tag detected -> READ mode");
    if (currentLocation == "DEFAULT") {
      logLine("Location registered as DEFAULT. Reregister device.");
      return;
    }
    String rawData = readTag_simple(serial);
    Serial.println(rawData);
    if (rawData != "") { 
      // Split the string at the pipe '|'
      int splitIndex = rawData.indexOf('|');
      String tagId = rawData.substring(0, splitIndex);
      String catOnTag = rawData.substring(splitIndex + 1);
      
      // -------- REGISTER FIRST (CHECK HAPPENS HERE) --------
      dashLine("Establishing connection with Google Sheets...");
      String regUrl = "/macros/s/" + DEPLOYMENT_ID + "/exec"
                      + "?op=register"
                      + "&tag_id=" + urlEncode(tagId)
                      + "&cat=" + urlEncode(catOnTag)
                      + "&location=" + urlEncode(currentLocation);

      String regResult = sendToGoogleSheet(regUrl);
      regResult.trim();

      dashLine("Register result: " + regResult);
    }
    
    logLine("Remove tag...");
    waitForTagRemoval();
    resetRFID();
    delay(150);
    return;
  }

  // ========= MODE: WRITE =========
  if (currentMode == MODE_WRITE) {
  // Stop dashboard logging
    logToDashboard = false;

    // ✅ Only require buffer data in WRITE mode
    if (!pendingCat.length() || !pendingLocation.length() || !pendingTs.length()) return;
    if (millis() - lastBufferedMs < BUFFER_READY_DELAY) return;

    // ✅ keep your existing “buffer must exist” checks
    // if (!pendingCat.length()) return;
    // if (millis() - lastBufferedMs < BUFFER_READY_DELAY) return;
    ledBusy();   // Yellow ON while registering + writing

    // (At this point currentMode must be MODE_WRITE)
    dashLine("Tag detected -> WRITE mode");

    String tagId = uidToString(serial);

    // -------- WRITE TAG ONLY IF REGISTER OK --------
    Serial.println(isPythonDataValid); 
    if (isPythonDataValid == false) {
      logLine("RFID write aborted: Python flagged data as INVALID.");
      ledFail();        // Red ON
    } 
    else {
      dashLine("Establishing connection with Google Sheets...");
      // -------- REGISTER FIRST (CHECK HAPPENS HERE) --------
      String regUrl = "/macros/s/" + DEPLOYMENT_ID + "/exec"
                      + "?op=register"
                      + "&tag_id=" + urlEncode(tagId)
                      + "&cat=" + urlEncode(pendingCat)
                      + "&location=" + urlEncode(pendingLocation);

      String regResult = sendToGoogleSheet(regUrl);
      regResult.trim();

      dashLine("Register result: " + regResult);
      
      // If duplicate / failed, do NOT write to tag
      if (regResult.indexOf("OK") < 0) {
        if (regResult.indexOf("Tag already registered") >= 0) {
          ledFail();   // Red ON
          Serial.println("Duplicate: already registered. NOT writing tag.");
        } else if (regResult.indexOf("Missing") >= 0) {
          ledFail();   // Red ON
          Serial.println("Missing parameters. NOT writing tag.");
        } else {
          ledFail();   // Red ON
          Serial.println("Register failed / unexpected. NOT writing tag.");
        }

        pendingCat = "";

        Serial.println("Remove tag...");
        waitForTagRemoval();
        resetRFID();
        delay(800);
        ledsOff();
        return;
      }

      delay(200); // small pause before RFID write
      // Data is valid, proceed with writing to the tag
      bool ok = writeToTag_simple(pendingCat, pendingTs, serial);
      
      if (!ok) {
        logLine("RFID write failed after register OK.");
        ledFail();      // Red ON
      } else {
        ledSuccess();   // Green ON
      }
    }
    
    // Clear buffer and wait for removal
    pendingCat = "";
    pendingLocation = "";
    pendingTs = "";
    isPythonDataValid = false;

    logLine("Remove tag...");
    waitForTagRemoval();
    resetRFID();
    delay(20);
    ledsOff();
    return;
  }

}



