//+------------------------------------------------------------------+
//|                                              FreeMT4Bridge.mq4   |
//|  免费 MT4 Socket 桥接 EA V3 - 自定义 # 分隔协议                   |
//|  改进: 多客户端并发接入 (最多4路), 独立超时检测                    |
//+------------------------------------------------------------------+
#property copyright "Free MT4 Bridge"
#property version   "3.00"
#property strict

#define INVALID_SOCKET      (-1)
#define SOCKET_ERROR        (-1)
uint FIONBIO_CMD = 0x8004667E;  // ioctlsocket: 设置非阻塞模式

#import "Ws2_32.dll"
   int WSAGetLastError();
   int socket(int af, int type, int protocol);
   int bind(int s, uchar& addr[], int namelen);
   int listen(int s, int backlog);
   int accept(int s, uchar& addr[], int& addrlen);
   int send(int s, const uchar& buf[], int len, int flags);
   int recv(int s, uchar& buf[], int len, int flags);
   int closesocket(int s);
   int ioctlsocket(int s, uint cmd, int& arg);
#import

input int ServerPort = 23232;
input bool AllowTrade = true;

int serverSocket = INVALID_SOCKET;
int clientSockets[4];
int clientCount = 0;
uchar recvBuf0[65536], recvBuf1[65536], recvBuf2[65536], recvBuf3[65536];
int recvLen0, recvLen1, recvLen2, recvLen3;
datetime lastActivity[4];
#define CLIENT_TIMEOUT_SEC 180  // 180秒无活动则断开（主循环约60秒一次）

//+------------------------------------------------------------------+
int OnInit()
{
   Print("[FreeBridge V3] Starting on port ", ServerPort);

   // 初始化所有 slot
   for(int j = 0; j < 4; j++) {
      clientSockets[j] = INVALID_SOCKET;
   }
   clientCount = 0;
   recvLen0 = 0; recvLen1 = 0; recvLen2 = 0; recvLen3 = 0;

   // 创建 TCP Socket
   serverSocket = socket(2, 1, 6);  // AF_INET, SOCK_STREAM, IPPROTO_TCP
   if(serverSocket == INVALID_SOCKET) {
      Print("[FreeBridge] socket() failed: ", WSAGetLastError());
      return INIT_FAILED;
   }

   // 设置非阻塞模式 (关键改进!)
   int mode = 1;
   if(ioctlsocket(serverSocket, FIONBIO_CMD, mode) != 0) {
      Print("[FreeBridge] WARNING: ioctlsocket failed: ", WSAGetLastError());
   } else {
      Print("[FreeBridge] Socket set to NON-BLOCKING mode");
   }

   // 绑定地址
   uchar addr[16];
   addr[0] = 2; addr[1] = 0;  // AF_INET
   addr[2] = (uchar)(ServerPort / 256);  // 端口高字节
   addr[3] = (uchar)(ServerPort % 256);  // 端口低字节
   for(int i = 4; i < 16; i++) addr[i] = 0;  // INADDR_ANY + padding

   if(bind(serverSocket, addr, 16) == SOCKET_ERROR) {
      Print("[FreeBridge] bind(", ServerPort, ") failed: ", WSAGetLastError());
      closesocket(serverSocket);
      return INIT_FAILED;
   }

   if(listen(serverSocket, 4) == SOCKET_ERROR) {
      Print("[FreeBridge] listen() failed: ", WSAGetLastError());
      closesocket(serverSocket);
      return INIT_FAILED;
   }

   Print("[FreeBridge] Server listening on port ", ServerPort);
   EventSetTimer(1);  // 每秒轮询一次
   return INIT_SUCCEEDED;
}
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   for(int i = 0; i < 4; i++) {
      if(clientSockets[i] != INVALID_SOCKET) closesocket(clientSockets[i]);
   }
   if(serverSocket != INVALID_SOCKET) closesocket(serverSocket);
   EventKillTimer();
   Print("[FreeBridge] Stopped (reason=", reason, ")");
}
//+------------------------------------------------------------------+
void OnTimer()
{
   // === 1. 接受新连接 ===
   if(clientCount < 4)
   {
      uchar addr[16];
      int addrlen = 16;
      int newSock = accept(serverSocket, addr, addrlen);

      if(newSock != INVALID_SOCKET) {
         // 找到第一个空槽
         for(int slot = 0; slot < 4; slot++) {
            if(clientSockets[slot] == INVALID_SOCKET) {
               clientSockets[slot] = newSock;
               lastActivity[slot] = TimeCurrent();
               clientCount++;
               Print("[FreeBridge] === Client connected (slot=", slot, ", total=", clientCount, ") ===");
               break;
            }
         }
      }
   }

   // === 2. 遍历所有连接: 超时检测 + 收数据 ===
   for(int c = 0; c < 4; c++)
   {
      if(clientSockets[c] == INVALID_SOCKET)
         continue;

      // 心跳超时
      if(TimeCurrent() - lastActivity[c] > CLIENT_TIMEOUT_SEC) {
         Print("[FreeBridge] Client timeout slot=", c, " (", CLIENT_TIMEOUT_SEC, "s), disconnecting");
         closesocket(clientSockets[c]);
         clientSockets[c] = INVALID_SOCKET;
         if(c==0) recvLen0=0; else if(c==1) recvLen1=0; else if(c==2) recvLen2=0; else recvLen3=0;
         clientCount--;
         continue;
      }

      // 接收数据
      uchar tmp[4096];
      int bytes = recv(clientSockets[c], tmp, 4096, 0);

      if(bytes > 0) {
         lastActivity[c] = TimeCurrent();
         for(int i = 0; i < bytes; i++) {
            if(c==0) { recvLen0 = (recvLen0 < 65535) ? recvLen0+1 : 65535; recvBuf0[recvLen0-1] = tmp[i]; }
            else if(c==1) { recvLen1 = (recvLen1 < 65535) ? recvLen1+1 : 65535; recvBuf1[recvLen1-1] = tmp[i]; }
            else if(c==2) { recvLen2 = (recvLen2 < 65535) ? recvLen2+1 : 65535; recvBuf2[recvLen2-1] = tmp[i]; }
            else { recvLen3 = (recvLen3 < 65535) ? recvLen3+1 : 65535; recvBuf3[recvLen3-1] = tmp[i]; }
            if(tmp[i] == '!') {
               string cmd = "";
               if(c==0) { cmd = CharArrayToString(recvBuf0, 0, recvLen0 - 1); recvLen0 = 0; }
               else if(c==1) { cmd = CharArrayToString(recvBuf1, 0, recvLen1 - 1); recvLen1 = 0; }
               else if(c==2) { cmd = CharArrayToString(recvBuf2, 0, recvLen2 - 1); recvLen2 = 0; }
               else { cmd = CharArrayToString(recvBuf3, 0, recvLen3 - 1); recvLen3 = 0; }
               ProcessCommand(cmd, clientSockets[c]);
            }
         }
      }
      else if(bytes == 0) {
         Print("[FreeBridge] Client disconnected gracefully slot=", c);
         closesocket(clientSockets[c]);
         clientSockets[c] = INVALID_SOCKET;
         if(c==0) recvLen0=0; else if(c==1) recvLen1=0; else if(c==2) recvLen2=0; else recvLen3=0;
         clientCount--;
      }
      else {
         int err = WSAGetLastError();
         if(err != 10035 && err != 10034) {
            Print("[FreeBridge] recv error slot=", c, ": ", err, ", disconnecting client");
            closesocket(clientSockets[c]);
            clientSockets[c] = INVALID_SOCKET;
            if(c==0) recvLen0=0; else if(c==1) recvLen1=0; else if(c==2) recvLen2=0; else recvLen3=0;
            clientCount--;
         }
      }
   }
}
//+------------------------------------------------------------------+
void ProcessCommand(string cmd, int sock)
{
   string parts[];
   int n = StringSplit(cmd, '#', parts);
   if(n < 2) { SendResponse("ERROR#bad command#", sock); return; }

   string fcode = parts[0];

   if(fcode == "F000") {
      SendResponse("F000#OK#", sock);
   }
   else if(fcode == "F001") {
      string resp = StringFormat("F001#OK#%s#%d#%s#Standard#%d#true#0#100.0#50.0#",
         AccountCompany(), AccountNumber(), AccountCurrency(), AccountLeverage());
      SendResponse(resp, sock);
   }
   else if(fcode == "F002") {
      double marginLevel = (AccountMargin() > 0) ? (AccountEquity() / AccountMargin() * 100) : 0;
      string resp = StringFormat("F002#OK#%.2f#%.2f#%.2f#%.2f#%.2f#%.2f#",
         AccountBalance(), AccountEquity(), AccountProfit(),
         AccountMargin(), marginLevel, AccountFreeMargin());
      SendResponse(resp, sock);
   }
   else if(fcode == "F020") {
      if(n < 3) { SendResponse("F020#ERROR#missing symbol#", sock); return; }
      string sym = parts[2];
      double bid = SymbolInfoDouble(sym, SYMBOL_BID);
      double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
      if(bid == 0) bid = MarketInfo(sym, MODE_BID);
      if(ask == 0) ask = MarketInfo(sym, MODE_ASK);
      datetime t = TimeCurrent();
      SendResponse(StringFormat("F020#OK#%d#%.5f#%.5f#%.5f#0#", (int)t, ask, bid, bid), sock);
   }
   else if(fcode == "F042") {
      if(n < 6) { SendResponse("F042#ERROR#bad params#", sock); return; }
      string sym = parts[2];
      int tf = (int)StringToInteger(parts[3]);
      int offset = (int)StringToInteger(parts[4]);
      int count = (int)StringToInteger(parts[5]);
      if(count > 5000) count = 5000;

      string resp = "F042#OK#";
      int barCount = 0;
      for(int i = offset; i < offset + count; i++) {
         datetime t = iTime(sym, tf, i);
         if(t == 0) break;
         resp += StringFormat("%d$%.5f$%.5f$%.5f$%.5f$%d#",
            (int)t, iOpen(sym, tf, i), iHigh(sym, tf, i),
            iLow(sym, tf, i), iClose(sym, tf, i), (int)iVolume(sym, tf, i));
         barCount++;
      }
      resp += "#";
      SendResponse(resp, sock);
   }
   else if(fcode == "F043") {
      // 获取K线 + MT4内置指标值（跟图表完全一致）
      // shift=0: 当前未完成K线(tick级), shift=1: 上一根已完成K线(固定值)
      if(n < 4) { SendResponse("F043#ERROR#bad params#", sock); return; }
      string sym = parts[2];
      int tf = (int)StringToInteger(parts[3]);
      int shift = 0;
      if(n >= 5) shift = (int)StringToInteger(parts[4]);

      // K线数据
      string resp = "F043#OK#";
      resp += StringFormat("%d$%.5f$%.5f$%.5f$%.5f$%d$",
         (int)iTime(sym, tf, shift),
         iOpen(sym, tf, shift),
         iHigh(sym, tf, shift),
         iLow(sym, tf, shift),
         iClose(sym, tf, shift),
         (int)iVolume(sym, tf, shift));

      // RSI(14)
      resp += StringFormat("%.2f$", iRSI(sym, tf, 14, PRICE_CLOSE, shift));
      // RSI(5)
      resp += StringFormat("%.2f$", iRSI(sym, tf, 5, PRICE_CLOSE, shift));
      // RSI(10)
      resp += StringFormat("%.2f$", iRSI(sym, tf, 10, PRICE_CLOSE, shift));
      // MFI(14)
      resp += StringFormat("%.2f$", iMFI(sym, tf, 14, shift));
      // BB upper/mid/lower (20,2)
      resp += StringFormat("%.5f$%.5f$%.5f$",
         iBands(sym, tf, 20, 2, 0, PRICE_CLOSE, MODE_UPPER, shift),
         iBands(sym, tf, 20, 2, 0, PRICE_CLOSE, MODE_MAIN, shift),
         iBands(sym, tf, 20, 2, 0, PRICE_CLOSE, MODE_LOWER, shift));
      // EMA9 / EMA21
      resp += StringFormat("%.5f$%.5f$",
         iMA(sym, tf, 9, 0, MODE_EMA, PRICE_CLOSE, shift),
         iMA(sym, tf, 21, 0, MODE_EMA, PRICE_CLOSE, shift));
      // SMA14 / SMA20 / SMA50
      resp += StringFormat("%.5f$%.5f$%.5f$",
         iMA(sym, tf, 14, 0, MODE_SMA, PRICE_CLOSE, shift),
         iMA(sym, tf, 20, 0, MODE_SMA, PRICE_CLOSE, shift),
         iMA(sym, tf, 50, 0, MODE_SMA, PRICE_CLOSE, shift));
      // ATR(14) / ATR(20)
      resp += StringFormat("%.5f$%.5f$",
         iATR(sym, tf, 14, shift),
         iATR(sym, tf, 20, shift));
      // ADX(14) / +DI / -DI
      resp += StringFormat("%.2f$%.2f$%.2f$",
         iADX(sym, tf, 14, PRICE_CLOSE, MODE_MAIN, shift),
         iADX(sym, tf, 14, PRICE_CLOSE, MODE_PLUSDI, shift),
         iADX(sym, tf, 14, PRICE_CLOSE, MODE_MINUSDI, shift));
      // MACD(12,26,9) main / signal
      resp += StringFormat("%.5f$%.5f$",
         iMACD(sym, tf, 12, 26, 9, PRICE_CLOSE, MODE_MAIN, shift),
         iMACD(sym, tf, 12, 26, 9, PRICE_CLOSE, MODE_SIGNAL, shift));
      // Stoch(5,3,3) K / D
      resp += StringFormat("%.2f$%.2f$",
         iStochastic(sym, tf, 5, 3, 3, MODE_SMA, 0, MODE_MAIN, shift),
         iStochastic(sym, tf, 5, 3, 3, MODE_SMA, 0, MODE_SIGNAL, shift));
      // Volume SMA(20)
      double volSum = 0;
      for(int vi = shift; vi < shift + 20; vi++) volSum += (double)iVolume(sym, tf, vi);
      resp += StringFormat("%.0f$", volSum / 20.0);

      resp += "#";
      SendResponse(resp, sock);
   }
   else if(fcode == "F061") {
      string resp = "F061#OK#";
      int total = OrdersTotal();
      for(int i = total - 1; i >= 0; i--) {
         if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
         if(OrderType() > OP_SELL) continue;
         string type = (OrderType() == OP_BUY) ? "BUY" : "SELL";
         resp += StringFormat("%d$%s$%s$%d$%.2f$%.5f$%d$%.5f$%.5f$%s$%.2f$%.2f$%.2f$",
            OrderTicket(), OrderSymbol(), type, OrderMagicNumber(),
            OrderLots(), OrderOpenPrice(), (int)OrderOpenTime(),
            OrderStopLoss(), OrderTakeProfit(), OrderComment(),
            OrderProfit(), OrderSwap(), OrderCommission());
      }
      resp += "#";
      SendResponse(resp, sock);
   }
   else if(fcode == "F062") {
      string resp = "F062#OK#";
      int total = OrdersHistoryTotal();
      for(int i = total - 1; i >= 0; i--) {
         if(!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY)) continue;
         if(OrderType() > OP_SELL) continue;
         string type = (OrderType() == OP_BUY) ? "BUY" : "SELL";
         resp += StringFormat("%d$%s$%s$%d$%.2f$%.5f$%d$%.5f$%d$%.2f$%.2f$%.2f$%.5f$%.5f$%s$",
            OrderTicket(), OrderSymbol(), type, OrderMagicNumber(),
            OrderLots(), OrderOpenPrice(), (int)OrderOpenTime(),
            OrderClosePrice(), (int)OrderCloseTime(),
            OrderProfit(), OrderSwap(), OrderCommission(),
            OrderStopLoss(), OrderTakeProfit(), OrderComment());
      }
      resp += "#";
      SendResponse(resp, sock);
   }
   else if(fcode == "F070") {
      if(n < 12) { SendResponse("F070#ERROR#bad params#", sock); return; }
      string sym = parts[2];
      string typeStr = StringLower(parts[3]);
      double volume = StringToDouble(parts[4]);
      double price = StringToDouble(parts[5]);
      int slippage = (int)StringToInteger(parts[6]);
      int magic = (int)StringToInteger(parts[7]);
      double sl = StringToDouble(parts[8]);
      double tp = StringToDouble(parts[9]);
      string comment = (n > 10) ? parts[10] : "";

      int cmdType = (typeStr == "buy") ? OP_BUY : OP_SELL;
      double openPrice = (typeStr == "buy") ? MarketInfo(sym, MODE_ASK) : MarketInfo(sym, MODE_BID);
      if(price > 0) openPrice = price;

      if(!AllowTrade) { SendResponse("F070#ERROR#trading disabled#", sock); return; }

      int ticket = OrderSend(sym, cmdType, volume, openPrice, slippage, sl, tp, comment, magic, 0, clrNONE);
      if(ticket > 0) {
         SendResponse(StringFormat("F070#OK#%d#ORDER_OPEN#", ticket), sock);
         Print("[FreeBridge] Order opened: ", typeStr, " ", sym, " ", volume, " ticket=", ticket);
      } else {
         int err = GetLastError();
         SendResponse(StringFormat("F070#ERROR#OrderSend failed error %d#%d#", err, -1), sock);
         Print("[FreeBridge] OrderSend failed: ", err);
      }
   }
   else if(fcode == "F071") {
      if(n < 3) { SendResponse("F071#ERROR#bad params#", sock); return; }
      int ticket = (int)StringToInteger(parts[2]);
      bool ok = ClosePosition(ticket);
      if(ok) SendResponse("F071#OK#ORDER_CLOSED#", sock);
      else SendResponse(StringFormat("F071#ERROR#close failed error %d#", GetLastError()), sock);
   }
   else if(fcode == "F072") {
      if(n < 4) { SendResponse("F072#ERROR#bad params#", sock); return; }
      int ticket = (int)StringToInteger(parts[2]);
      double volume = StringToDouble(parts[3]);
      bool ok = ClosePositionPartial(ticket, volume);
      if(ok) SendResponse("F072#OK#ORDER_CLOSED#", sock);
      else SendResponse(StringFormat("F072#ERROR#partial close failed error %d#", GetLastError()), sock);
   }
   else if(fcode == "F075") {
      if(n < 5) { SendResponse("F075#ERROR#bad params#", sock); return; }
      int ticket = (int)StringToInteger(parts[2]);
      double sl = StringToDouble(parts[3]);
      double tp = StringToDouble(parts[4]);
      bool ok = ModifyPosition(ticket, sl, tp);
      if(ok) SendResponse("F075#OK#MODIFIED#", sock);
      else SendResponse(StringFormat("F075#ERROR#modify failed error %d#", GetLastError()), sock);
   }
   else {
      SendResponse(StringFormat("%s#ERROR#unknown command#", fcode), sock);
   }
}
//+------------------------------------------------------------------+
void SendResponse(string response, int sock)
{
   if(sock == INVALID_SOCKET) return;

   uchar buf[];
   int len = StringToCharArray(response, buf);
   if(len <= 0) return;

   if(buf[len-1] == 0) len--;
   buf[len] = '!';
   len++;

   send(sock, buf, len, 0);
}
//+------------------------------------------------------------------+
bool ClosePosition(int ticket)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--) {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderTicket() == ticket) {
         double price = (OrderType() == OP_BUY) ?
            MarketInfo(OrderSymbol(), MODE_BID) :
            MarketInfo(OrderSymbol(), MODE_ASK);
         color clr = (OrderType() == OP_BUY) ? clrRed : clrBlue;
         bool ok = OrderClose(ticket, OrderLots(), price, 10, clr);
         if(!ok) Print("[FreeBridge] OrderClose error: ", GetLastError());
         return ok;
      }
   }
   Print("[FreeBridge] Ticket ", ticket, " not found");
   return false;
}
//+------------------------------------------------------------------+
bool ClosePositionPartial(int ticket, double volume)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--) {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderTicket() == ticket) {
         double price = (OrderType() == OP_BUY) ?
            MarketInfo(OrderSymbol(), MODE_BID) :
            MarketInfo(OrderSymbol(), MODE_ASK);
         color clr = (OrderType() == OP_BUY) ? clrRed : clrBlue;
         bool ok = OrderClose(ticket, volume, price, 10, clr);
         if(!ok) Print("[FreeBridge] PartialClose error: ", GetLastError());
         return ok;
      }
   }
   return false;
}
//+------------------------------------------------------------------+
bool ModifyPosition(int ticket, double sl, double tp)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--) {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderTicket() == ticket) {
         bool ok = OrderModify(ticket, OrderOpenPrice(), sl, tp, 0, clrNONE);
         if(!ok) Print("[FreeBridge] OrderModify error: ", GetLastError());
         return ok;
      }
   }
   return false;
}
//+------------------------------------------------------------------+
string StringLower(string s)
{
   string r = "";
   for(int i = 0; i < StringLen(s); i++) {
      ushort c = StringGetCharacter(s, i);
      if(c >= 65 && c <= 90) c = c + 32;
      r += CharToStr((uchar)c);
   }
   return r;
}
//+------------------------------------------------------------------+
