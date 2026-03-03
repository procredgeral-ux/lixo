"""API router for indicators management"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional

from core.database import get_db
from models import Indicator
from schemas import (
    IndicatorCreate,
    IndicatorUpdate,
    IndicatorResponse,
    IndicatorsListResponse,
    MessageResponse
)

router = APIRouter(tags=["indicators"])


@router.get("/", response_model=IndicatorsListResponse)
async def list_indicators(
    skip: int = 0,
    limit: int = 100,
    is_active: Optional[bool] = None,
    type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all indicators with optional filters"""
    stmt = select(Indicator)
    
    if is_active is not None:
        stmt = stmt.where(Indicator.is_active == is_active)
    
    if type is not None:
        stmt = stmt.where(Indicator.type == type)
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()
    
    # Get indicators
    stmt = stmt.order_by(Indicator.name).offset(skip).limit(limit)
    result = await db.execute(stmt)
    indicators = result.scalars().all()
    
    # Convert to response models
    indicator_responses = [
        IndicatorResponse(
            id=ind.id,
            name=ind.name,
            type=ind.type,
            description=ind.description,
            parameters=ind.parameters or {},
            is_active=ind.is_active,
            is_default=ind.is_default,
            created_at=ind.created_at
        )
        for ind in indicators
    ]
    
    return IndicatorsListResponse(
        indicators=indicator_responses,
        total=total,
        page=1,
        page_size=limit
    )


@router.get("/default", response_model=IndicatorsListResponse)
async def list_default_indicators(db: AsyncSession = Depends(get_db)):
    """List all default system indicators"""
    stmt = select(Indicator).where(
        Indicator.is_default == True,
        Indicator.is_active == True
    ).order_by(Indicator.name)
    
    result = await db.execute(stmt)
    indicators = result.scalars().all()
    
    # Convert to response models
    indicator_responses = [
        IndicatorResponse(
            id=ind.id,
            name=ind.name,
            type=ind.type,
            description=ind.description,
            parameters=ind.parameters or {},
            is_active=ind.is_active,
            is_default=ind.is_default,
            created_at=ind.created_at
        )
        for ind in indicators
    ]
    
    return IndicatorsListResponse(
        indicators=indicator_responses,
        total=len(indicators),
        page=1,
        page_size=len(indicators)
    )


@router.get("/{indicator_id}", response_model=IndicatorResponse)
async def get_indicator(indicator_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific indicator by ID"""
    stmt = select(Indicator).where(Indicator.id == indicator_id)
    result = await db.execute(stmt)
    indicator = result.scalar_one_or_none()
    
    if not indicator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Indicator with ID {indicator_id} not found"
        )
    
    return indicator


@router.get("/name/{name}", response_model=IndicatorResponse)
async def get_indicator_by_name(name: str, db: AsyncSession = Depends(get_db)):
    """Get a specific indicator by name"""
    stmt = select(Indicator).where(Indicator.name == name)
    result = await db.execute(stmt)
    indicator = result.scalar_one_or_none()
    
    if not indicator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Indicator with name '{name}' not found"
        )
    
    return indicator


@router.post("/", response_model=IndicatorResponse, status_code=status.HTTP_201_CREATED)
async def create_indicator(indicator: IndicatorCreate, db: AsyncSession = Depends(get_db)):
    """Create a new indicator"""
    # Check if indicator with same name already exists
    stmt = select(Indicator).where(Indicator.name == indicator.name)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Indicator with name '{indicator.name}' already exists"
        )
    
    # Create new indicator
    db_indicator = Indicator(**indicator.model_dump())
    db.add(db_indicator)
    await db.commit()
    await db.refresh(db_indicator)
    
    return db_indicator


@router.put("/{indicator_id}", response_model=IndicatorResponse)
async def update_indicator(
    indicator_id: str,
    indicator_update: IndicatorUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update an existing indicator"""
    stmt = select(Indicator).where(Indicator.id == indicator_id)
    result = await db.execute(stmt)
    indicator = result.scalar_one_or_none()
    
    if not indicator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Indicator with ID {indicator_id} not found"
        )
    
    # Update fields
    update_data = indicator_update.model_dump()
    for field, value in update_data.items():
        setattr(indicator, field, value)
    
    await db.commit()
    await db.refresh(indicator)
    
    return indicator


@router.delete("/{indicator_id}", response_model=MessageResponse)
async def delete_indicator(indicator_id: str, db: AsyncSession = Depends(get_db)):
    """Delete an indicator"""
    stmt = select(Indicator).where(Indicator.id == indicator_id)
    result = await db.execute(stmt)
    indicator = result.scalar_one_or_none()
    
    if not indicator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Indicator with ID {indicator_id} not found"
        )
    
    # Prevent deletion of default indicators
    if indicator.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete default system indicators"
        )
    
    await db.delete(indicator)
    await db.commit()
    
    return MessageResponse(message=f"Indicator {indicator_id} deleted successfully")


@router.post("/seed-defaults", response_model=MessageResponse)
async def seed_default_indicators(db: AsyncSession = Depends(get_db)):
    """Seed default system indicators"""
    default_indicators = [
        {
            "name": "RSI",
            "type": "rsi",
            "description": "Relative Strength Index - measures momentum",
            "parameters": {
                "period": 14
            },
            "is_default": True
        },
        {
            "name": "MACD",
            "type": "macd",
            "description": "Moving Average Convergence Divergence",
            "parameters": {
                "fast_period": 12,
                "slow_period": 26,
                "signal_period": 9
            },
            "is_default": True
        },
        {
            "name": "Bollinger Bands",
            "type": "bollinger_bands",
            "description": "Bollinger Bands - volatility indicator",
            "parameters": {
                "period": 20,
                "std_dev": 2.0
            },
            "is_default": True
        },
        {
            "name": "SMA",
            "type": "sma",
            "description": "Simple Moving Average",
            "parameters": {
                "period": 20
            },
            "is_default": True
        },
        {
            "name": "EMA",
            "type": "ema",
            "description": "Exponential Moving Average",
            "parameters": {
                "period": 20
            },
            "is_default": True
        },
        {
            "name": "Stochastic",
            "type": "stochastic",
            "description": "Stochastic Oscillator",
            "parameters": {
                "k_period": 14,
                "d_period": 3,
                "smooth": 3
            },
            "is_default": True
        },
        {
            "name": "ATR",
            "type": "atr",
            "description": "Average True Range - volatility measure",
            "parameters": {
                "period": 14
            },
            "is_default": True
        },
        {
            "name": "CCI",
            "type": "cci",
            "description": "Commodity Channel Index",
            "parameters": {
                "period": 20
            },
            "is_default": True
        },
        {
            "name": "Williams %R",
            "type": "williams_r",
            "description": "Williams Percent Range",
            "parameters": {
                "period": 14
            },
            "is_default": True
        },
        {
            "name": "ROC",
            "type": "roc",
            "description": "Rate of Change",
            "parameters": {
                "period": 12
            },
            "is_default": True
        },
        {
            "name": "Parabolic SAR",
            "type": "parabolic_sar",
            "description": "Parabolic Stop and Reverse - trend reversal indicator",
            "parameters": {
                "initial_af": 0.02,
                "max_af": 0.2,
                "step_af": 0.02
            },
            "is_default": True
        },
        {
            "name": "Ichimoku Cloud",
            "type": "ichimoku_cloud",
            "description": "Ichimoku Kinko Hyo - comprehensive trend indicator",
            "parameters": {
                "tenkan_period": 9,
                "kijun_period": 26,
                "senkou_span_b_period": 52,
                "chikou_shift": 26
            },
            "is_default": True
        },
        {
            "name": "Money Flow Index",
            "type": "money_flow_index",
            "description": "MFI - momentum indicator with volume",
            "parameters": {
                "period": 14
            },
            "is_default": True
        },
        {
            "name": "ADX",
            "type": "average_directional_index",
            "description": "Average Directional Index - trend strength indicator",
            "parameters": {
                "period": 14
            },
            "is_default": True
        },
        {
            "name": "Keltner Channels",
            "type": "keltner_channels",
            "description": "Keltner Channels - volatility bands",
            "parameters": {
                "ema_period": 20,
                "atr_period": 20,
                "multiplier": 2.0
            },
            "is_default": True
        },
        {
            "name": "Donchian Channels",
            "type": "donchian_channels",
            "description": "Donchian Channels - price channel indicator",
            "parameters": {
                "period": 20
            },
            "is_default": True
        },
        {
            "name": "Heiken Ashi",
            "type": "heiken_ashi",
            "description": "Heiken Ashi - filtered price candles",
            "parameters": {},
            "is_default": True
        },
        {
            "name": "Pivot Points",
            "type": "pivot_points",
            "description": "Pivot Points - support and resistance levels",
            "parameters": {},
            "is_default": True
        },
        {
            "name": "Supertrend",
            "type": "supertrend",
            "description": "Supertrend - trend following indicator",
            "parameters": {
                "atr_period": 10,
                "multiplier": 3.0
            },
            "is_default": True
        },
        {
            "name": "Fibonacci Retracement",
            "type": "fibonacci_retracement",
            "description": "Fibonacci Retracement - support/resistance levels",
            "parameters": {
                "lookback": 50
            },
            "is_default": True
        },
        {
            "name": "Zonas",
            "type": "zonas",
            "description": "Support and Resistance Zones",
            "parameters": {
                "swing_period": 5,
                "zone_strength": 2,
                "zone_tolerance": 0.005,
                "min_zone_width": 0.003,
                "atr_multiplier": 0.5
            },
            "is_default": True
        },
        {
            "name": "VWAP",
            "type": "vwap",
            "description": "Volume Weighted Average Price - volume-based price benchmark",
            "parameters": {
                "period": 14
            },
            "is_default": True
        },
        {
            "name": "OBV",
            "type": "obv",
            "description": "On Balance Volume - cumulative volume flow indicator",
            "parameters": {},
            "is_default": True
        }
    ]
    
    created_count = 0
    for indicator_data in default_indicators:
        stmt = select(Indicator).where(Indicator.name == indicator_data["name"])
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if not existing:
            db_indicator = Indicator(**indicator_data)
            db.add(db_indicator)
            created_count += 1
    
    await db.commit()
    
    return MessageResponse(
        message=f"Seeded {created_count} default indicators successfully"
    )
