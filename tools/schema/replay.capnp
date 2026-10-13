@0xa0d896b9b1aa39dd;



# Increment for any incompatible replay, map, or playback semantics change.
# Keep Replay.formatVersion at the same field ordinal and its default at 0.
const replayFormatVersion :UInt32 = 2;

# A mirror of engine/include/engine/event.h

enum Team {
  a @0;
  b @1;
}

enum Direction {
  north @0;
  east @1;
  south @2;
  west @3;
}

enum DragonDeathReason {
  hitWall @0;
  hitSelf @1;
  hitOtherBody @2;
  hitHeadToHead @3;
  noValidAction @4;
}

enum DebugShape {
  line @0;
  dot @1;
}

enum GameEndReason {
  teamEliminated @0;
  roundLimit @1;
}

struct Point {
  x @0 :Int32;
  y @1 :Int32;
}

struct DebugDraw {
  shape @0 :DebugShape;
  from @1 :Point;
  to @2 :Point;
  red @3 :UInt8;
  green @4 :UInt8;
  blue @5 :UInt8;
}

struct PlayerAction {
  union {
    move @0 :List(Direction);
    split @1 :Int32;
    suicide @2 :Void;
  }
}

struct EventRoundStart {
  round @0 :Int32;
}

struct EventTurnStart {
  id @0 :Int32;
}

struct InstructionUsage {
  count @0 :UInt64;
  exceeded @1 :Bool;
}

struct EventPearlCountdown {
  tile @0 :Point;
  countdown @1 :Int32;
}

struct EventTileChange {
  tile @0 :Point;
  hasPearl @1 :Bool;
}

struct EventDragonAction {
  id @0 :Int32;
  action @1 :PlayerAction; # null when tle
  instructions @2 :InstructionUsage; # absent in older/unmetered replays
  tle @3 :Bool;
}

struct EventEngineLog {
  id @0 :Int32;
  text @1 :Text;
}

struct EventDragonLog {
  id @0 :Int32;
  text @1 :Text;
}

struct EventDragonIndicator {
  id @0 :Int32;
  text @1 :Text;
}

struct EventDebugDraw {
  id @0 :Int32;
  draw @1 :DebugDraw;
}

struct EventDragonUpdate {
  id @0 :Int32;
  facing @1 :Direction;
  head @2 :Point;
  tail @3 :Point;
}

struct EventDragonSplit {
  parentId @0 :Int32;
  childId @1 :Int32;
  team @2 :Team;
  childFacing @3 :Direction;
  parentBody @4 :List(Point);
  childBody @5 :List(Point);
}

struct EventDragonDeath {
  id @0 :Int32;
  reason @1 :DragonDeathReason;
}

struct EventSonarPing {
  senderId @0 :Int32;
  direction @1 :Direction;
  value @2 :UInt32;
  origin @3 :Point;
  end @4 :Point;
  union {
    noHit @5 :Void;
    hitId @6 :Int32;
  }
  value64 @7 :UInt64;
  hitKind @8 :SonarHitKind;
}

enum SonarHitKind {
  unknown @0;
  empty @1;
  kelp @2;
  ally @3;
  allyHead @4;
  enemy @5;
  enemyHead @6;
}

struct Event {
  union {
    roundStart @0 :EventRoundStart;
    turnStart @1 :EventTurnStart;
    pearlCountdown @2 :EventPearlCountdown;
    tileChange @3 :EventTileChange;
    dragonAction @4 :EventDragonAction;
    engineLog @5 :EventEngineLog;
    dragonLog @6 :EventDragonLog;
    dragonIndicator @7 :EventDragonIndicator;
    debugDraw @8 :EventDebugDraw;
    dragonUpdate @9 :EventDragonUpdate;
    dragonSplit @10 :EventDragonSplit;
    dragonDeath @11 :EventDragonDeath;
    sonarPing @12 :EventSonarPing;
  }
}

struct TeamStanding {
  dragonCount @0 :Int32;
  longestDragon @1 :Int32;
  totalLength @2 :Int32;
}

struct GameResult {
  terminated @0 :Bool;
  endReason @1 :GameEndReason;
  union {
    noWinner @2 :Void;
    winner @3 :Team;
  }
  teamA @4 :TeamStanding;
  teamB @5 :TeamStanding;
}

struct Replay {
  map @0 :Text; # the .map file verbatim
  botA @1 :Text;
  botB @2 :Text;
  events @3 :List(Event);
  result @4 :GameResult;
  formatVersion @5 :UInt32; # 0 = legacy replays without a version
}
