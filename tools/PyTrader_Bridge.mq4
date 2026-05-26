//+------------------------------------------------------------------+
//|                                              PyTrader_Bridge.mq4 |
//| PyTrader EA - Socket bridge between MT4 and Python               |
//| Place this in: MQL4/Experts/PyTrader_Bridge.mq4                  |
//| Then compile in MetaEditor and load to any chart                 |
//+------------------------------------------------------------------+
#property copyright "PyTrader Bridge"
#property version   "1.00"
#property strict

#import "Ws2_32.dll"
   int socket(int af, int type, int protocol);
   int bind(int s, uint& addr[], int namelen);
   int listen(int s, int backlog);
   int accept(int s, uint& addr[], int& addrlen);
   int recv(int s, uchar& buf[], int len, int flags);
   int send(int s, uchar& buf[], int len, int flags);
   int closesocket(int s);
   int WSAGetLastError();
#import

input int ServerPort = 9988;  // Socket listen port

int serverSocket = INVALID_SOCKET;
int clientSocket = INVALID_SOCKET;

//+------------------------------------------------------------------+
int OnInit()
{
   EventSetTimer(1);
   Print("[PyTrader] Initializing on port ", ServerPort);
   StartServer();
   return(INIT_SUCCEEDED);
}
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(clientSocket != INVALID_SOCKET) closesocket(clientSocket);
   if(serverSocket != INVALID_SOCKET) closesocket(serverSocket);
   Print("[PyTrader] Stopped");
}
//+------------------------------------------------------------------+
void OnTimer()
{
   if(clientSocket == INVALID_SOCKET)
   {
      AcceptClient();
      return;
   }

   // Read data from Python
   uchar buffer[4096];
   int bytes = recv(clientSocket, buffer, 4096, 0);
   if(bytes > 0)
   {
      string command = CharArrayToString(buffer, 0, bytes);
      string response = ProcessCommand(command);
      SendResponse(response);
   }
   else if(bytes == SOCKET_ERROR)
   {
      int err = WSAGetLastError();
      if(err != 10035) // WSAEWOULDBLOCK
      {
         Print("[PyTrader] Client disconnected, error: ", err);
         closesocket(clientSocket);
         clientSocket = INVALID_SOCKET;
      }
   }
}
//+------------------------------------------------------------------+
void StartServer()
{
   serverSocket = socket(2, 1, 6); // AF_INET, SOCK_STREAM, IPPROTO_TCP
   if(serverSocket == INVALID_SOCKET)
   {
      Print("[PyTrader] Failed to create socket: ", WSAGetLastError());
      return;
   }

   uint addr[2];
   addr[0] = (ServerPort << 16) | 0x020000; // AF_INET + port (host byte order)
   addr[1] = 0; // INADDR_ANY

   if(bind(serverSocket, addr, 8) == SOCKET_ERROR)
   {
      Print("[PyTrader] Failed to bind: ", WSAGetLastError());
      return;
   }

   if(listen(serverSocket, 1) == SOCKET_ERROR)
   {
      Print("[PyTrader] Failed to listen: ", WSAGetLastError());
      return;
   }

   Print("[PyTrader] Server listening on port ", ServerPort);
}
//+------------------------------------------------------------------+
void AcceptClient()
{
   if(serverSocket == INVALID_SOCKET) return;

   uint addr[2];
   int addrlen = 8;
   clientSocket = accept(serverSocket, addr, addrlen);

   if(clientSocket != INVALID_SOCKET)
   {
      Print("[PyTrader] Client connected");
   }
}
//+------------------------------------------------------------------+
string ProcessCommand(string command)
{
   // Parse JSON-like command and respond
   // Simple protocol: {"cmd":"get_account_info"} etc.

   if(StringFind(command, "get_account_info") >= 0)
   {
      return FormatAccountInfo();
   }
   if(StringFind(command, "get_all_open_positions") >= 0)
   {
      return FormatPositions();
   }
   if(StringFind(command, "get_symbol_info") >= 0)
   {
      return FormatSymbolInfo(command);
   }
   if(StringFind(command, "get_rates") >= 0)
   {
      return FormatRates(command);
   }

   return "{\"ret_code\":-1,\"error\":\"unknown command\"}";
}
//+------------------------------------------------------------------+
string FormatAccountInfo()
{
   return StringFormat(
      "{\"ret_code\":0,\"data\":{"
      "\"login\":%d,"
      "\"balance\":%.2f,"
      "\"equity\":%.2f,"
      "\"margin\":%.2f,"
      "\"free_margin\":%.2f,"
      "\"currency\":\"%s\","
      "\"leverage\":%d}}",
      AccountNumber(),
      AccountBalance(),
      AccountEquity(),
      AccountMargin(),
      AccountFreeMargin(),
      AccountCurrency(),
      AccountLeverage()
   );
}
//+------------------------------------------------------------------+
string FormatPositions()
{
   string result = "{\"ret_code\":0,\"data\":[";
   int total = OrdersTotal();
   bool first = true;

   for(int i = total - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderSymbol() == Symbol())
      {
         if(!first) result += ",";
         result += StringFormat(
            "{\"ticket\":%d,\"symbol\":\"%s\",\"type\":\"%s\","
            "\"lots\":%.2f,\"open_price\":%.5f,\"current_price\":%.5f,"
            "\"stop_loss\":%.5f,\"take_profit\":%.5f,\"profit\":%.2f,"
            "\"swap\":%.2f,\"commission\":%.2f,\"magic\":%d,"
            "\"comment\":\"%s\",\"open_time\":\"%s\"}",
            OrderTicket(),
            OrderSymbol(),
            OrderType() == OP_BUY ? "OP_BUY" : (OrderType() == OP_SELL ? "OP_SELL" : "PENDING"),
            OrderLots(),
            OrderOpenPrice(),
            (OrderType() <= OP_SELL) ? OrderClosePrice() : 0,
            OrderStopLoss(),
            OrderTakeProfit(),
            OrderProfit(),
            OrderSwap(),
            OrderCommission(),
            OrderMagicNumber(),
            OrderComment(),
            TimeToString(OrderOpenTime())
         );
         first = false;
      }
   }
   result += "]}";
   return result;
}
//+------------------------------------------------------------------+
string FormatSymbolInfo(string command)
{
   string symbol = Symbol();
   double bid = MarketInfo(symbol, MODE_BID);
   double ask = MarketInfo(symbol, MODE_ASK);

   return StringFormat(
      "{\"ret_code\":0,\"data\":{"
      "\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f}}",
      symbol, bid, ask
   );
}
//+------------------------------------------------------------------+
string FormatRates(string command)
{
   // Parse timeframe and count from command
   int tf = 60; // default H1
   int count = 100;

   return "{\"ret_code\":0,\"data\":[]}";
}
//+------------------------------------------------------------------+
void SendResponse(string response)
{
   if(clientSocket == INVALID_SOCKET) return;

   uchar buf[];
   StringToCharArray(response, buf);
   send(clientSocket, buf, ArraySize(buf), 0);
}
//+------------------------------------------------------------------+

// NOTE: This is a minimal skeleton. Full implementation requires:
// 1. Complete JSON parsing for all commands
// 2. Proper rate fetching with different timeframes
// 3. Order execution (open/close/modify)
// 4. Consider using the ready-made PyTrader from:
//    https://github.com/danmi1258/PyTrader-python-mt4-mt5-trading-api-connector-drag-n-drop
