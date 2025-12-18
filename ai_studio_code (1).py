import os
import json
import random
import asyncio
import time
from datetime import datetime
from hashlib import sha256
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

import requests # For IPFS
import numpy as np # For audio data
import matplotlib.pyplot as plt # For waveform image
from PIL import Image # For image handling
from io import BytesIO # For image/audio buffers

# Solana SDKs
from solana.rpc.api import Client # Core RPC client
from solana.publickey import PublicKey # For public keys
from solana.keypair import Keypair # For wallet management
from solana.transaction import Transaction, TransactionInstruction # For building transactions
from solana.system_program import create_account, SYS_PROGRAM_ID, transfer # System program instructions
from spl.token.program import Token, TOKEN_PROGRAM_ID # SPL Token program instructions
from spl.associated_token.program import create_associated_token_account # ATA program instructions

# Metaplex Token Metadata SDK (Requires AnchorPy)
# pip install anchorpy mpl-token-metadata
from anchorpy import Provider, Wallet # AnchorPy for Provider/Wallet context
from mpl_token_metadata import types, program, program_id as METADATA_PROGRAM_ID # Metaplex SDK

# Drift Protocol SDK
# pip install driftpy
from driftpy.clearing_house import ClearingHouse # Core Drift client
from driftpy.types import MarketType, OrderType, PositionDirection # Drift enums/types
from driftpy.constants.markets import get_markets_and_oracles # Market data constants
from driftpy.accounts import get_perp_market_account # Fetch market data

# For environment variables
try:
    from dotenv import load_dotenv
    load_dotenv() # Load .env file
    print("Loaded environment variables from .env file.")
except ImportError:
    print("`python-dotenv` not installed. Assuming environment variables are set.")


# ==============================================================================
# 0. CONFIGURATION
# ==============================================================================

@dataclass
class SolanaConfig:
    RPC_URL: str = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    
    # Common Devnet Token Mints (verify on solscan.io/token/<MINT>?cluster=devnet)
    DEVNET_USDC_MINT = PublicKey(os.getenv("DEVNET_USDC_MINT", "4zMMC9qqXTsQBUGcTDj54gKGEJ5zXNf5q2VdY8kF3eWv")) # Example Devnet USDC (USDCet)
    DEVNET_SOL_MINT = PublicKey("So11111111111111111111111111111111111111112") # SOL is always this

    # Program IDs (Metaplex often stable, Token/ATA are fixed)
    METAPLEX_PROGRAM_ID = PublicKey("metaqbxxUerdq28cj1RbTGWuRxFUNDBzXPFjcXbCDWL")
    TOKEN_PROGRAM_ID = PublicKey("TokenkegQfeZyiNwAJbNbGKPFXAbZ5dXtogkK9uLk2CN")
    ASSOCIATED_TOKEN_PROGRAM_ID = PublicKey("ATokenGPvbdGVL8RjR2KmnBf4ezW22P1PSy9S1oePG")
    
    # Drift Protocol Devnet Program ID (VERIFY LATEST FROM DRIFTPY DOCS/GITHUB)
    DRIFT_PROGRAM_ID = PublicKey(os.getenv("DRIFT_PROGRAM_ID", "dRiftyHA39MWEz3m9aBN5AjsyfvZgjgApERadPcsSsR"))
    
    # IPFS Pinata API Keys (User must set in .env or Hugging Face Space secrets)
    PINATA_API_KEY = os.getenv("PINATA_API_KEY")
    PINATA_SECRET_API_KEY = os.getenv("PINATA_SECRET_API_KEY")

    # Paths
    KEYPAIR_PATH = os.getenv("DEVNET_KEYPAIR_PATH", "./devnet-keypair.json")
    TEMP_AUDIO_DIR = "./temp_audio_assets"

# Ensure temp directory exists
os.makedirs(SolanaConfig.TEMP_AUDIO_DIR, exist_ok=True)


# ==============================================================================
# 1. WALLET UTILITIES
# ==============================================================================

def load_keypair_from_file(path: str) -> Keypair:
    """Loads a Solana Keypair from a JSON file."""
    try:
        with open(path, 'r') as f:
            secret = json.load(f)
        return Keypair.from_secret_key(bytes(secret))
    except FileNotFoundError:
        raise FileNotFoundError(f"Keypair file not found at: {path}. Please create one and fund it (e.g., solana-keygen new --outfile {path})")
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON in keypair file: {path}")
    except Exception as e:
        raise ValueError(f"Failed to load keypair from {path}: {e}")

# ==============================================================================
# 2. IPFS CLIENT (Pinata)
# ==============================================================================

class IPFSClient:
    def __init__(self, api_base_url: str = "https://api.pinata.cloud", 
                 api_key: Optional[str] = None, api_secret: Optional[str] = None):
        if not api_key or not api_secret:
            raise ValueError("Pinata API Key and Secret are required for IPFS operations.")
        self.api_base_url = api_base_url
        self.headers = {
            "pinata_api_key": api_key,
            "pinata_secret_api_key": api_secret
        }
        print(f"[IPFS] Client initialized for {api_base_url} (Pinata).")

    def pin_file(self, file_path: str, name: str) -> str:
        """Uploads a file to Pinata and returns its IPFS CID."""
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (name, f)}
                response = requests.post(
                    f"{self.api_base_url}/pinning/pinFileToIPFS", 
                    files=files, headers=self.headers, timeout=60
                )
                response.raise_for_status()
                cid = response.json()['IpfsHash']
                print(f"  --> Pinned {file_path} to IPFS: ipfs://{cid}")
                return f"ipfs://{cid}"
        except requests.exceptions.RequestException as e:
            raise IOError(f"Failed to pin file to IPFS: {e}")

    def pin_json(self, json_data: Dict, name: str) -> str:
        """Uploads JSON data to Pinata and returns its IPFS CID."""
        try:
            payload = {
                "pinataMetadata": {"name": name},
                "pinataContent": json_data
            }
            response = requests.post(
                f"{self.api_base_url}/pinning/pinJSONToIPFS", 
                json=payload, headers=self.headers, timeout=30
            )
            response.raise_for_status()
            cid = response.json()['IpfsHash']
            print(f"  --> Pinned JSON metadata to IPFS: ipfs://{cid}")
            return f"ipfs://{cid}"
        except requests.exceptions.RequestException as e:
            raise IOError(f"Failed to pin JSON to IPFS: {e}")

# ==============================================================================
# 3. FART NFT MINTER (Real Devnet Minting)
# ==============================================================================

class FartNFTMinter:
    def __init__(self, rpc_client: Client):
        self.rpc_client = rpc_client
        print(f"[NFT Minter] Initialized for RPC: {rpc_client.cluster_name}.")

    async def mint_fart_nft(self, payer_keypair: Keypair, metadata_uri: str, nft_name: str, nft_symbol: str) -> Dict:
        """
        Mints a single NFT on Solana Devnet using Metaplex Token Metadata.
        This is a complex operation requiring multiple transactions.
        """
        print(f"\n[NFT Minter] Initiating NFT Mint for '{nft_name}' on Devnet...")
        payer_pubkey = payer_keypair.public_key()

        # 1. Generate new Mint Keypair for the NFT
        mint_keypair = Keypair()
        mint_pubkey = mint_keypair.public_key()
        print(f"  - New NFT Mint Address: {mint_pubkey.to_base58()}")

        # 2. Derive PDA for Metaplex Metadata Account
        metadata_pda, _ = PublicKey.find_program_address(
            [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint_pubkey)],
            METADATA_PROGRAM_ID
        )
        print(f"  - Metaplex Metadata PDA: {metadata_pda.to_base58()}")

        # 3. Get ATA for the payer for this new Mint
        ata_pubkey, _ = PublicKey.find_program_address(
            [bytes(payer_pubkey), bytes(SolanaConfig.TOKEN_PROGRAM_ID), bytes(mint_pubkey)],
            SolanaConfig.ASSOCIATED_TOKEN_PROGRAM_ID
        )
        print(f"  - Payer's ATA for NFT: {ata_pubkey.to_base58()}")

        # --- Construct and Send Transaction ---
        # A single transaction combining most instructions for efficiency
        instructions: List[TransactionInstruction] = []
        signers: List[Keypair] = [payer_keypair, mint_keypair]

        # A) Create Mint Account (requires rent exemption)
        mint_rent = self.rpc_client.get_minimum_balance_for_rent_exemption(Token.span_for_decimals(0))['result']
        instructions.append(create_account(
            from_pubkey=payer_pubkey,
            new_account_pubkey=mint_pubkey,
            lamports=mint_rent,
            space=Token.span_for_decimals(0),
            program_id=SolanaConfig.TOKEN_PROGRAM_ID
        ))

        # B) Initialize Mint Account
        instructions.append(Token.initialize_mint(
            program_id=SolanaConfig.TOKEN_PROGRAM_ID,
            mint=mint_pubkey,
            mint_authority=payer_pubkey,
            freeze_authority=payer_pubkey,
            decimals=0 # NFTs are non-divisible
        ))
        
        # C) Create Associated Token Account for the payer
        instructions.append(create_associated_token_account(
            payer=payer_pubkey,
            owner=payer_pubkey,
            mint=mint_pubkey
        ))

        # D) Mint 1 Token to the ATA
        instructions.append(Token.mint_to(
            program_id=SolanaConfig.TOKEN_PROGRAM_ID,
            mint=mint_pubkey,
            dest=ata_pubkey,
            mint_authority=payer_pubkey,
            amount=1, # Mint 1 token for the NFT
            signers=[payer_keypair]
        ))

        # E) Create Metaplex Metadata Account (using mpl-token-metadata SDK)
        # This part requires AnchorPy Provider context
        provider = Provider(self.rpc_client, Wallet(payer_keypair))
        
        # Ensure name and symbol fit Metaplex limits
        nft_name = nft_name[:32]
        nft_symbol = nft_symbol[:10]

        met_inst = program.create_create_metadata_account_v2_instruction(
            types.CreateMetadataAccountArgsV2(
                data=types.DataV2(
                    name=nft_name,
                    symbol=nft_symbol,
                    uri=metadata_uri,
                    seller_fee_basis_points=0, # 0% creator fees for simplicity, specify if needed
                    creators=None, # List of creator public keys and shares
                    collection=None,
                    uses=None,
                ),
                is_mutable=False, # Set to False for true immutability (hardens NFT)
                collection_details=None,
            ),
            accounts={
                "metadata": metadata_pda,
                "mint": mint_pubkey,
                "mint_authority": payer_pubkey,
                "payer": payer_pubkey,
                "update_authority": payer_pubkey, # Payer initially controls update
                "system_program": SYS_PROGRAM_ID,
                "rent": SYS_PROGRAM_ID, # Rent account for simplicity
                "token_program": SolanaConfig.TOKEN_PROGRAM_ID,
                "associated_token_program": SolanaConfig.ASSOCIATED_TOKEN_PROGRAM_ID,
            },
            program_id=METADATA_PROGRAM_ID,
        )
        instructions.append(met_inst)

        # F) Set Mint Authority to None (freeze NFT)
        # This makes the NFT non-mintable and non-freezable after creation.
        instructions.append(Token.set_authority(
            program_id=SolanaConfig.TOKEN_PROGRAM_ID,
            token_account=mint_pubkey,
            current_authority=payer_pubkey,
            new_authority=None, # Set to None to disable minting
            authority_type=0, # MintTokens authority
            signers=[payer_keypair]
        ))
        
        # --- Send Transaction ---
        try:
            transaction = Transaction()
            transaction.add(*instructions)
            
            # Fetch recent blockhash
            recent_blockhash_resp = self.rpc_client.get_latest_blockhash('finalized')
            transaction.recent_blockhash = recent_blockhash_resp['result']['value']['blockhash']
            transaction.fee_payer = payer_pubkey

            # Transaction must be signed by both payer and the new mint keypair
            signed_txn = transaction.sign(*signers)
            
            print(f"  - Sending transaction for NFT mint (approx. {len(instructions)} instructions)...")
            tx_hash = self.rpc_client.send_raw_transaction(signed_txn.serialize(), opts={"skip_preflight": True}).get('result')
            if not tx_hash:
                raise Exception("Failed to get transaction hash after sending.")

            print(f"  - Transaction sent: {tx_hash}")
            print("  - Confirming transaction... (this may take a few seconds)")
            
            # CRITICAL: Implement robust confirmation loop with timeouts
            confirmation_status = self.rpc_client.confirm_transaction(tx_hash, commitment='finalized')
            if confirmation_status['result']['value']['err']:
                raise Exception(f"Transaction failed on-chain: {confirmation_status['result']['value']['err']}")

            print(f"  - Transaction Confirmed: {tx_hash}")
            return {"token_address": mint_pubkey.to_base58(), "tx_hash": tx_hash, "status": "success"}

        except Exception as e:
            print(f"  - ERROR during NFT minting: {e}")
            return {"token_address": None, "tx_hash": None, "status": "failed", "error": str(e)}

# ==============================================================================
# 4. DRIFT CLIENT (Real Devnet Shorting)
# ==============================================================================

class DriftClient:
    def __init__(self, rpc_client: Client, payer_keypair: Keypair, drift_program_id: PublicKey):
        self.rpc_client = rpc_client
        self.payer_keypair = payer_keypair
        self.drift_program_id = drift_program_id
        self.clearing_house: Optional[ClearingHouse] = None
        print(f"[Drift] Client initialized for Devnet program: {drift_program_id.to_base58()}")

    async def initialize_user_if_needed(self):
        """Initializes a user's account on Drift if it doesn't already exist."""
        print("[Drift] Initializing user account if needed...")
        try:
            provider = Provider(self.rpc_client, Wallet(self.payer_keypair))
            self.clearing_house = await ClearingHouse.load(provider, self.drift_program_id)
            
            is_initialized = await self.clearing_house.is_user_initialized()
            if not is_initialized:
                print("  - User account not initialized. Sending init transaction...")
                init_tx = await self.clearing_house.initialize_user()
                await init_tx.execute()
                await init_tx.confirm_transaction()
                print("  - User account initialized.")
            else:
                print("  - User account already initialized.")
        except Exception as e:
            print(f"  - ERROR initializing Drift user: {e}")
            self.clearing_house = None # Ensure clearing_house is None on failure

    async def deposit_collateral(self, amount_usdc: float):
        """Deposits USDC into the Drift margin account."""
        if not self.clearing_house:
            print("  - ERROR: Drift ClearingHouse not initialized. Cannot deposit.")
            return

        print(f"[Drift] Depositing {amount_usdc} USDC collateral...")
        try:
            # Assumes user has USDC in their associated token account
            deposit_tx = await self.clearing_house.deposit(
                int(amount_usdc * (10**6)), # Convert to micro-units
                SolanaConfig.DEVNET_USDC_MINT
            )
            await deposit_tx.execute()
            await deposit_tx.confirm_transaction()
            print(f"  - Deposited {amount_usdc} USDC successfully.")
        except Exception as e:
            print(f"  - ERROR depositing USDC: {e}")

    async def get_perp_market_data(self, market_index: int) -> Optional[Dict]:
        """Fetches order book and funding rate for a specific perp market."""
        if not self.clearing_house:
            print("  - ERROR: Drift ClearingHouse not initialized. Cannot fetch market data.")
            return None
        
        try:
            print(f"[Drift] Fetching market data for market index {market_index}...")
            # Use real driftpy to fetch market accounts
            market_state = await get_perp_market_account(self.rpc_client, self.drift_program_id, market_index)
            
            # Simplified parsing - real data structures are more complex
            # For order book, you'd typically subscribe to a WebSocket or query specific APIs
            # Here, we derive from market state and assume some base price for simplicity
            
            # This is a highly simplified estimate from market_state for conceptual orderbook
            # Actual orderbook depth would require more complex queries/Websockets.
            price_base = market_state.amm.last_bid_price / (10**6) if market_state.amm.last_bid_price else 0
            price_ask = market_state.amm.last_ask_price / (10**6) if market_state.amm.last_ask_price else 0

            # If prices are zero (no recent trades), fall back to some estimate or return None
            if price_base == 0:
                price_base = market_state.amm.quote_asset_reserve / market_state.amm.base_asset_reserve # CPMM price
                price_ask = price_base * 1.001
                price_base = price_base * 0.999
            
            funding_rate = market_state.amm.next_funding_rate_long / (10**9) if market_state.amm.next_funding_rate_long else 0 # Example

            return {
                "market_index": market_index,
                "best_bid": price_base,
                "best_ask": price_ask,
                "funding_rate": funding_rate, # Actual funding rate from perp market
                "liquidity_at_bid": 1000.0, # Placeholder
                "liquidity_at_ask": 1000.0, # Placeholder
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            print(f"  - ERROR fetching Drift market data: {e}")
            return None

    async def open_short_position(self, market_index: int, amount_sol: float, price_limit: float) -> Optional[str]:
        """Opens a short position on a perp market."""
        if not self.clearing_house:
            print("  - ERROR: Drift ClearingHouse not initialized. Cannot open short position.")
            return None
        
        print(f"[Drift] Opening SHORT {amount_sol} SOL on market index {market_index} at limit {price_limit}...")
        try:
            # Convert human-readable amount to base asset amount (e.g., micro units for SOL)
            base_asset_amount_i = int(amount_sol * (10**6)) 
            price_i = int(price_limit * (10**6)) # Convert to micro-units for quote asset

            order_params = types.OrderParams(
                market_index=market_index,
                market_type=MarketType.Perp,
                direction=PositionDirection.Short,
                order_type=OrderType.Limit,
                base_asset_amount=base_asset_amount_i,
                price=price_i,
                # Other parameters: user_order_id, reduce_only, post_only, etc.
            )
            order_tx = await self.clearing_house.place_perp_order(order_params)
            await order_tx.execute()
            await order_tx.confirm_transaction()
            print(f"  - Drift Short Order placed successfully. Tx: {order_tx.txid}")
            return order_tx.txid
        except Exception as e:
            print(f"  - ERROR opening Drift short position: {e}")
            return None

    async def close_position(self, market_index: int) -> Optional[str]:
        """Closes an open position on a perp market."""
        if not self.clearing_house:
            print("  - ERROR: Drift ClearingHouse not initialized. Cannot close position.")
            return None
        
        print(f"[Drift] Closing position on market index {market_index}...")
        try:
            close_tx = await self.clearing_house.close_perp_position(market_index)
            await close_tx.execute()
            await close_tx.confirm_transaction()
            print(f"  - Drift Position Closed successfully. Tx: {close_tx.txid}")
            return close_tx.txid
        except Exception as e:
            print(f"  - ERROR closing Drift position: {e}")
            return None


# ==============================================================================
# 5. ARBITRAGE/SHORTING STRATEGY (Conceptual)
# ==============================================================================

class ArbitrageStrategy:
    def __init__(self):
        self.min_profit_threshold = 0.05 # Minimum profit in USDC after fees
        self.fees_per_leg = 0.0005 # 0.05% taker fee (conceptual average)
        self.solana_tx_fee_usdc = 0.0001 # Devnet transaction cost approximation
        self.arb_amount_sol = 0.5 # Amount of SOL to attempt to arb

    async def find_drift_perp_short_opportunity(self, drift_perp_data: Dict) -> Optional[Dict]:
        """
        Looks for a simple shorting opportunity on Drift SOL-PERP based on a
        conceptual 'overvaluation' or high funding rate.
        This is not a true arbitrage but a directional shorting example.
        """
        if not drift_perp_data or drift_perp_data["best_bid"] == 0 or drift_perp_data["best_ask"] == 0:
            return None

        current_price = drift_perp_data["best_bid"] # Price to sell (short)
        funding_rate = drift_perp_data["funding_rate"]

        # Simple strategy: If current price is "high" AND funding rate is positive (we get paid to short)
        # This is very naive; real strategies are complex.
        if current_price > 115.0 and funding_rate > 0.00005: # Conceptual thresholds
            # Calculate potential profit from closing later (very speculative)
            # For a true short, profit comes from price dropping.
            # Here, we consider the funding rate benefit for holding short.
            
            # Estimate profit from funding rate for 1 hour
            estimated_profit_from_funding = funding_rate * self.arb_amount_sol * current_price # USDC
            
            # Simple "profit" if price drops by $1, minus fees
            conceptual_price_drop_profit = self.arb_amount_sol * 1.0 * (1 - self.fees_per_leg) - self.solana_tx_fee_usdc

            total_conceptual_profit = estimated_profit_from_funding + conceptual_price_drop_profit
            
            if total_conceptual_profit > self.min_profit_threshold:
                return {
                    "type": "Short SOL-PERP (Drift)",
                    "profit_usdc": total_conceptual_profit,
                    "short_price": current_price,
                    "amount_sol": self.arb_amount_sol,
                    "market_index": drift_perp_data["market_index"],
                    "funding_rate": funding_rate,
                    "timestamp": datetime.now().isoformat()
                }
        return None

    async def execute_short_strategy(self, opportunity: Dict, drift_client: DriftClient) -> List[str]:
        """Executes the identified shorting opportunity on Drift."""
        print(f"\n[Strategy] Executing shorting opportunity: {opportunity['type']}...")
        tx_hashes = []
        try:
            if opportunity["type"] == "Short SOL-PERP (Drift)":
                perp_tx = await drift_client.open_short_position(
                    opportunity["market_index"], 
                    opportunity["amount_sol"], 
                    opportunity["short_price"]
                )
                if perp_tx:
                    tx_hashes.append(perp_tx)
            
            print(f"  - Short strategy initiated. Transaction IDs: {tx_hashes}")
            return tx_hashes
        except Exception as e:
            print(f"  - ERROR during short strategy execution: {e}")
            return []

# ==============================================================================
# 6. MAIN ORCHESTRATOR (`app.py` for Hugging Face Space)
# ==============================================================================

async def main_orchestrator():
    print("🚀 Fart Tokenization & Shorting System Starting (Solana Devnet, No Mocks)...")

    # --- 0. Setup Configuration and Wallet ---
    try:
        payer_keypair = load_keypair_from_file(SolanaConfig.KEYPAIR_PATH)
    except Exception as e:
        print(f"FATAL: Could not load Devnet keypair. Ensure '{SolanaConfig.KEYPAIR_PATH}' exists and is valid. Error: {e}")
        return # Exit if keypair isn't loaded securely

    payer_pubkey = payer_keypair.public_key()
    print(f"Devnet Wallet Loaded: {payer_pubkey.to_base58()}")

    rpc_client = Client(SolanaConfig.RPC_URL)
    print(f"Connected to Solana Devnet RPC: {SolanaConfig.RPC_URL}")

    # --- 1. IPFS Client (Pinata) ---
    try:
        ipfs_client = IPFSClient(
            api_key=SolanaConfig.PINATA_API_KEY,
            api_secret=SolanaConfig.PINATA_SECRET_API_KEY
        )
    except ValueError as e:
        print(f"FATAL: IPFS client setup failed: {e}. Ensure PINATA_API_KEY and PINATA_SECRET_API_KEY are set.")
        return

    # --- 2. NFT Minter ---
    nft_minter = FartNFTMinter(rpc_client)

    # --- 3. Drift Client ---
    drift_client = DriftClient(rpc_client, payer_keypair, SolanaConfig.DRIFT_PROGRAM_ID)
    await drift_client.initialize_user_if_needed()
    await drift_client.deposit_collateral(20.0) # Deposit 20 Devnet USDC for trading

    # --- 4. Arbitrage/Shorting Strategy ---
    arb_strategy = ArbitrageStrategy()

    # --- Main Loop ---
    fart_token_mint_address = None
    drift_sol_perp_market_index = 0 # Default SOL-PERP market index on Drift Devnet

    while True:
        current_time = datetime.now().strftime('%H:%M:%S')
        print(f"\n[{current_time}] --- Fart System Cycle ---")

        # --- A. Fart Tokenization (NFT Minting) Example ---
        if not fart_token_mint_address:
            print("[Tokenization] Attempting to mint a Fart NFT...")
            try:
                # 1. Generate conceptual fart attributes and dummy audio/visual
                fart_id = f"devnet_fart_{random.randint(1000, 9999)}"
                fart_name = f"Devnet Fart #{fart_id}"
                fart_symbol = "DFRT"
                fart_description = f"A uniquely loud Devnet fart at {current_time}. ID: {fart_id}"
                
                # Create a dummy audio file for IPFS (silent WAV)
                dummy_audio_path = os.path.join(SolanaConfig.TEMP_AUDIO_DIR, f"{fart_id}.wav")
                sample_rate = 44100
                duration_s = 0.5
                dummy_audio = np.zeros(int(sample_rate * duration_s)).astype(np.int16)
                from scipy.io.wavfile import write as write_wav
                write_wav(dummy_audio_path, sample_rate, dummy_audio)

                # Generate a simple waveform image for NFT 'image'
                fig, ax = plt.subplots(figsize=(6, 2))
                ax.plot(np.linspace(0, duration_s, len(dummy_audio)), dummy_audio, color='blue')
                ax.set_title("Fart Waveform (Conceptual)")
                ax.axis('off') # Hide axes for a cleaner NFT image
                buf = BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1)
                plt.close(fig)
                buf.seek(0)
                dummy_image_path = os.path.join(SolanaConfig.TEMP_AUDIO_DIR, f"{fart_id}.png")
                Image.open(buf).save(dummy_image_path)

                # 2. Pin audio & image to IPFS
                audio_ipfs_uri = ipfs_client.pin_file(dummy_audio_path, f"{fart_id}.wav")
                image_ipfs_uri = ipfs_client.pin_file(dummy_image_path, f"{fart_id}.png")
                
                # 3. Create Metaplex metadata
                metadata_json = {
                    "name": fart_name,
                    "symbol": fart_symbol,
                    "description": fart_description,
                    "image": image_ipfs_uri,
                    "animation_url": audio_ipfs_uri,
                    "attributes": [{"trait_type": "FartID", "value": fart_id}],
                    "properties": {
                        "files": [{"uri": audio_ipfs_uri, "type": "audio/wav"}],
                        "category": "audio"
                    }
                }
                metadata_ipfs_uri = ipfs_client.pin_json(metadata_json, f"{fart_id}_metadata.json")

                # 4. Mint NFT
                mint_result = await nft_minter.mint_fart_nft(
                    payer_keypair, metadata_ipfs_uri, fart_name, fart_symbol
                )
                if mint_result["status"] == "success":
                    fart_token_mint_address = mint_result["token_address"]
                    print(f"Successfully minted Fart NFT: {fart_token_mint_address}")
                else:
                    print(f"Failed to mint Fart NFT: {mint_result.get('error', 'Unknown error')}")
                
                # Clean up dummy files
                if os.path.exists(dummy_audio_path): os.remove(dummy_audio_path)
                if os.path.exists(dummy_image_path): os.remove(dummy_image_path)
            except Exception as e:
                print(f"  - ERROR during NFT minting process: {e}")
        else:
            print(f"[Tokenization] Fart NFT already minted (or attempted): {fart_token_mint_address}")


        # --- B. Fart Shorting (General Shorting on Drift SOL-PERP) Example ---
        if drift_client.clearing_house: # Only proceed if Drift client is initialized
            print("[Shorting] Monitoring Drift Protocol for SOL-PERP opportunities...")
            drift_market_data = await drift_client.get_perp_market_data(drift_sol_perp_market_index)
            
            if drift_market_data:
                print(f"  - Drift SOL-PERP Bid: {drift_market_data['best_bid']:.4f}, Ask: {drift_market_data['best_ask']:.4f}, Funding: {drift_market_data['funding_rate']:.6f}")
                
                opportunity = await arb_strategy.find_drift_perp_short_opportunity(drift_market_data)

                if opportunity:
                    print(f"🎉 Shorting Opportunity Found: {opportunity['type']} with conceptual profit {opportunity['profit_usdc']:.4f} USDC")
                    await arb_strategy.execute_short_strategy(opportunity, drift_client)
                    # For a real system, you'd implement a close condition or a target profit/loss.
                    print("  - Short position opened. Will attempt to close after a short delay for demonstration.")
                    await asyncio.sleep(60) # Hold short for 60 seconds
                    await drift_client.close_position(drift_sol_perp_market_index)
                else:
                    print("No profitable shorting opportunity found on Drift for SOL-PERP.")
            else:
                print("  - Could not retrieve Drift market data.")
        else:
            print("[Shorting] Drift client not fully initialized. Skipping shorting strategy.")


        await asyncio.sleep(10) # Wait 10 seconds before next cycle


# ==============================================================================
# ENTRY POINT FOR HUGGING FACE SPACES
# ==============================================================================

# This is the standard entry point for an `app.py` in Hugging Face Spaces.
# It should trigger the main asynchronous function.
if __name__ == "__main__":
    print("Starting Fart Tokenization & Shorting App...")
    # Run the main asynchronous orchestrator
    asyncio.run(main_orchestrator())