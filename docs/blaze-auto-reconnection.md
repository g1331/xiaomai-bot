# Blaze Auto-Reconnection Implementation

## Problem
When Blaze connections drop, users had to manually run `/blaze relogin` before being able to query player lists again. This caused poor user experience.

## Solution  
Implemented automatic reconnection in `BF1BlazeManager.get_player_list()` that:

1. **Detects connection failures** - Catches connection errors and data processing failures
2. **Automatically retries once** - Cleans up old connections and attempts reconnection  
3. **Preserves timeout behavior** - Timeout errors still fail immediately to avoid long waits
4. **Maintains existing functionality** - All parameters and features work as before

## Benefits

### Commands that now auto-reconnect:
- `-谁在玩` / `-谁在捞` (Who's playing queries)
- Server clearing operations (kick all players)
- `-sk` / `-searchkick` (Search and kick operations) 
- `-move` / `-换边` (Move player operations)
- And any other functionality using `BF1BlazeManager.get_player_list()`

### User Experience:
- **Before**: Error message → User runs `/blaze relogin` → User retries command
- **After**: Automatic reconnection → User gets result seamlessly

## Implementation Details

### Core Logic:
```python
async def get_player_list(game_ids, origin=False, platoon=False):
    # Try query first
    result = await _perform_query(retry_attempt=False)
    
    # If connection failed, auto-retry once
    if result == "需要重连":
        logger.info("正在执行自动重连...")
        # Clean up old connection
        await cleanup_connection()
        # Retry
        result = await _perform_query(retry_attempt=True)
        if isinstance(result, dict):
            logger.success("自动重连成功!")
    
    return result
```

### Error Handling:
- **Connection errors**: Auto-retry once
- **Timeout errors**: Fail immediately (no retry)
- **Data processing failures**: Auto-retry once  
- **Second failure**: Return error (prevent infinite loops)

### Connection Cleanup:
- Properly closes old sockets before retry
- Removes clients from manager cache
- Uses same reconnection logic as manual `/blaze relogin`

## Testing

### Test Coverage:
- `test_blaze_auto_reconnect.py` - Unit tests for various failure scenarios
- `demo_auto_reconnect.py` - Integration demo showing user experience
- Syntax validation and code style consistency checks

### Test Scenarios:
1. Connection initialization failure → auto-retry → success
2. Send operation failure → auto-retry → success  
3. Timeout error → immediate failure (no retry)
4. Data processing failure → auto-retry → success

## Compatibility

- **Backward compatible**: All existing code continues to work unchanged
- **Same API**: Method signature and return values unchanged
- **Consistent patterns**: Follows existing reconnection patterns in codebase
- **Proper logging**: Uses same logging style as existing code

## Result

Users no longer need to manually run `/blaze relogin` when connections drop. The system handles reconnection automatically, making the bot significantly more reliable and user-friendly.