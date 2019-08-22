
class FrascoPushConnection extends EventTarget {
  constructor(url, token, autoConnect = true) {
    super();
    this.url = url;
    this.token = token;
    if (autoConnect) {
      this.connect();
    }
  }
  connect(options) {
    if (this.socket) {
      return Promise.resolve(this.socket.id);
    }
    return new Promise((resolve, reject) => {
      options = Object.assign({forceNew: true}, options || {});
      options.query = Object.assign(options.query || {}, {token: this.token});
      this.socket = io(this.url, options);
      this.rooms = {};
      this.socket.on('connect', () => {
        this.dispatchEvent(new Event('connected'));
        this.dispatchEvent(new CustomEvent('socketIdChanged', {detail: {id: this.socket.id}}));
        resolve(this.socket.id);
      });
      this.socket.on('reconnecting', (attempts) => {
        if (attempts > 5) {
          this.dispatchEvent(new Event('connectionLost'));
        }
      });
      this.socket.on('reconnect', () => {
        this.dispatchEvent(new CustomEvent('socketIdChanged', {detail: {id: this.socket.id}}));
        Object.keys(this.rooms).forEach((name) => {
          this.rooms[name].join(true).catch(() => {
            delete this.rooms[name];
          });
        });
        this.dispatchEvent(new Event('reconnected'));
      });
      this.socket.on('disconnect', () => {
        this.dispatchEvent(new Event('disconnected'));
      });
    });
  }
  setUserInfo(data) {
    this.socket.emit('set', data);
  }
  getUserInfo() {
    return new Promise((resolve, reject) => {
      this.socket.emit('get', data => resolve(data));
    });
  }
  join(roomName) {
    if (roomName in this.rooms) {
      return Promise.resolve(this.rooms[roomName]);
    }
    return new Promise((resolve, reject) => {
      var room = new FrascoPushRoom(this, roomName);
      room.join().then(() => {
        this.rooms[roomName] = room;
        room.addEventListener('left', () => {
          delete this.rooms[roomName];
        });
        resolve(room);
      }).catch(() => {
        reject();
      });
    });
  }
  on(event, listener) {
    return this.socket.on(event, listener);
  }
  close() {
    this.socket.close();
    this.socket = null;
    this.rooms = {};
  }
}

class FrascoPushRoom extends EventTarget {
  constructor(conn, name) {
    super();
    this.conn = conn;
    this.name = name;
    this.joined = false;
    this.members = {};
    this.subs = [];

    this.on('joined', (user) => {
      this.members[user.sid] = user.info;
      this._updateMembers();
    });

    this.on('left', (sid) => {
      if (typeof(this.members[sid]) !== 'undefined') {
        delete this.members[sid];
      }
      this._updateMembers();
    });
  }
  join(force) {
    return new Promise((resolve, reject) => {
      if (this.joined && !force) {
        resolve();
        return;
      }
      this.conn.socket.emit('join', {room: this.name}, (members) => {
        if (members) {
          this.joined = true;
          this._updateMembers(members);
          this.dispatchEvent(new Event('joined'));
          resolve();
        } else {
          reject();
        }
      });
    });
  }
  on(event, listener) {
    const e = `${this.name}:${event}`;
    this.conn.socket.on(e, listener);
    this.subs.push(() => {
      this.conn.socket.off(e, listener);
    });
  }
  removeAllListeners() {
    this.subs.forEach((off) => off());
    this.subs = [];
  }
  emit(event, data) {
    this.conn.socket.emit('broadcast', {event: event, data: data, room: this.name});
  }
  refreshMembers() {
    this.conn.socket.emit('members', {room: this.name}, (members) => {
      this._updateMembers(members);
    });
  }
  leave() {
    this.conn.socket.emit('leave', {room: this.name});
    this.joined = false;
    this._updateMembers({});
    this.removeAllListeners();
    this.dispatchEvent(new Event('left'));
  }
  _updateMembers(members) {
    if (members) {
      this.members = members;
    }
    this.dispatchEvent(new Event('membersUpdated'));
  }
}
