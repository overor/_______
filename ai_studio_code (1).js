// app.js
import { Connection, PublicKey, Transaction } from '@solana/web3.js';
// In a real application, you would also import Zeta Markets SDK and Jupiter/Raydium SDKs.
// For this 'latency agnostic' modeling, we will simulate data fetching and trade construction.

// --- Configuration ---
const SOLANA_RPC_URL = 'https://api.mainnet-beta.solana.com'; // Use a robust RPC
const connection = new Connection(SOLANA_RPC_URL, 'confirmed');
const MODEL_FEES_PERCENTAGE = 0.0007; // 0.07% assumed taker fee per leg for model
const FUNDING_RATE_PERIOD_HOURS = 8; // Zeta funding usually paid every 8 hours

// --- DOM Elements ---
const walletStatusDiv = document.getElementById('wallet-status');
const lastRefreshDiv = document.getElementById('last-refresh');
const connectWalletBtn = document.getElementById('connectWallet');
const refreshDataBtn = document.getElementById('refreshData');
const generalStatusDiv = document.getElementById('general-status');
const spotPriceSpan = document.getElementById('spot-price');
const zetaMarkPriceSpan = document.getElementById('zeta-mark-price');
const zetaFundingRateSpan = document.getElementById('zeta-funding-rate');
const zetaBidSpan = document.getElementById('zeta-bid');
const zetaAskSpan = document.getElementById('zeta-ask');
const opportunityResultDiv = document.getElementById('opportunity-result');
const initiateTradeBtn = document.getElementById('initiateTrade');
const tradeStatusDiv = document.getElementById('trade-status');

// --- Global State ---
let userPublicKey = null;
let currentMarketData = {
    spotPrice: 0,
    zetaMarkPrice: 0,
    zetaFundingRateAnnualized: 0,
    zetaBid: 0,
    zetaAsk: 0
};

// --- Functions ---

async function connectWallet() {
    try {
        const { solana } = window;
        if (!solana || !solana.isPhantom) {
            generalStatusDiv.className = 'status-message error';
            generalStatusDiv.innerHTML = '<p>Solana wallet (e.g., Phantom) not found. Please install and refresh.</p>';
            return;
        }

        const resp = await solana.connect();
        userPublicKey = new PublicKey(resp.publicKey.toString());
        walletStatusDiv.textContent = `${userPublicKey.toBase58().substring(0, 6)}... Connected`;
        generalStatusDiv.className = 'status-message success';
        generalStatusDiv.textContent = 'Wallet connected successfully!';
        initiateTradeBtn.disabled = false;
        await fetchDataAndModel(); // Fetch data after connecting
    } catch (err) {
        console.error("Wallet connection failed:", err);
        generalStatusDiv.className = 'status-message error';
        generalStatusDiv.innerHTML = `<p>Wallet connection failed: ${err.message}</p>`;
    }
}

// --- SIMULATED DATA FETCHING (Replace with real SDK calls) ---
async function fetchSimulatedMarketData() {
    // In a real application:
    // 1. Use Jupiter/Raydium SDKs for spot price via their APIs/RPC.
    // 2. Use Zeta Markets SDK (e.g., @zeta-markets/sdk) to fetch perp prices (mark, bid, ask) and funding rates.
    //    This would involve knowing the specific market index for SOL-PERP.

    // Simulate some realistic-ish fluctuations
    const baseSOLPrice = 120 + (Math.random() - 0.5) * 5; // SOL around 117.5-122.5
    const spotPrice = baseSOLPrice + (Math.random() - 0.5) * 0.2; // Small spot variance
    const zetaMarkPrice = baseSOLPrice + (Math.random() - 0.5) * 0.5; // Perp price might differ
    const zetaBid = zetaMarkPrice - (Math.random() * 0.1 + 0.05); // Bid is below mark
    const zetaAsk = zetaMarkPrice + (Math.random() * 0.1 + 0.05); // Ask is above mark

    // Simulate funding rate (can be positive or negative)
    const zetaFundingRateAnnualized = ((Math.random() - 0.5) * 0.05).toFixed(4); // -2.5% to +2.5% annualized

    await new Promise(resolve => setTimeout(resolve, 500 + Math.random() * 500)); // Simulate network delay

    return {
        spotPrice: parseFloat(spotPrice.toFixed(4)),
        zetaMarkPrice: parseFloat(zetaMarkPrice.toFixed(4)),
        zetaFundingRateAnnualized: parseFloat(zetaFundingRateAnnualized),
        zetaBid: parseFloat(zetaBid.toFixed(4)),
        zetaAsk: parseFloat(zetaAsk.toFixed(4))
    };
}

async function fetchDataAndModel() {
    generalStatusDiv.className = 'status-message';
    generalStatusDiv.textContent = 'Fetching market data and modeling opportunities...';
    try {
        currentMarketData = await fetchSimulatedMarketData();

        spotPriceSpan.textContent = currentMarketData.spotPrice;
        zetaMarkPriceSpan.textContent = currentMarketData.zetaMarkPrice;
        zetaFundingRateSpan.textContent = (currentMarketData.zetaFundingRateAnnualized * 100).toFixed(2);
        zetaBidSpan.textContent = currentMarketData.zetaBid;
        zetaAskSpan.textContent = currentMarketData.zetaAsk;
        lastRefreshDiv.textContent = new Date().toLocaleTimeString();

        modelLatentOpportunity(currentMarketData);
        generalStatusDiv.className = 'status-message success';
        generalStatusDiv.textContent = 'Market data refreshed and model updated.';

    } catch (error) {
        console.error("Error fetching data:", error);
        generalStatusDiv.className = 'status-message error';
        generalStatusDiv.innerHTML = `<p>Error fetching market data: ${error.message}</p>`;
        // Reset displays
        spotPriceSpan.textContent = zetaMarkPriceSpan.textContent = zetaFundingRateSpan.textContent = zetaBidSpan.textContent = zetaAskSpan.textContent = 'Error';
        opportunityResultDiv.className = 'opportunity negative';
        opportunityResultDiv.textContent = 'Could not fetch data for modeling.';
    }
}

// --- Latent Opportunity Modeling ---
function modelLatentOpportunity(data) {
    const { spotPrice, zetaMarkPrice, zetaFundingRateAnnualized, zetaBid, zetaAsk } = data;

    let opportunityDescription = "No significant latent opportunity detected at this time (considering fees and model assumptions).";
    opportunityResultDiv.className = 'opportunity neutral';

    // Simplified Basis Calculation (Perp Price vs. Spot Price)
    const basis = (zetaMarkPrice - spotPrice);
    const basisPercentage = (basis / spotPrice) * 100;

    // Projected Funding Rate for next period
    const fundingPerPeriod = zetaFundingRateAnnualized / (365 * 24 / FUNDING_RATE_PERIOD_HOURS); // Daily rate / (365 * 24 / 8) periods

    // MODEL 1: Long Spot / Short Perp (Positive Basis + Negative Funding or Large Positive Basis)
    // If perp is significantly higher than spot (positive basis), and funding is not too high (or even negative)
    // Buy spot, short perp, expect convergence and/or collect negative funding
    if (basisPercentage > 0.5) { // If perp is 0.5% or more above spot
        // Calculate theoretical profit if holding until next funding payment and prices converge
        // Simplified: assume prices converge to spot after a period.
        const potentialFundingCollect = fundingPerPeriod * zetaMarkPrice; // per unit of SOL shorted
        const estimatedProfit = basis - (2 * MODEL_FEES_PERCENTAGE * spotPrice) + potentialFundingCollect; // Gross profit minus two legs of fees

        if (estimatedProfit > 0.1) { // Example threshold for meaningful profit (e.g., > $0.1 per SOL)
            opportunityDescription = `**LATENT OPPORTUNITY (Long Spot / Short Perp):** Zeta Perp is ${basisPercentage.toFixed(2)}% above Spot.`;
            opportunityDescription += `<br>Projected gain from convergence & funding: ~${estimatedProfit.toFixed(4)} USDC per SOL (before slippage).`;
            opportunityDescription += `<br>Action: Buy Spot SOL, Short SOL-PERP on Zeta. (Funding rate: ${(-fundingPerPeriod * 100).toFixed(4)}% per ${FUNDING_RATE_PERIOD_HOURS}h)`;
            opportunityResultDiv.className = 'opportunity positive';
        }
    }

    // MODEL 2: Short Spot / Long Perp (Negative Basis + Positive Funding or Large Negative Basis)
    // If spot is significantly higher than perp (negative basis), and funding is not too low (or even positive)
    // Sell spot, long perp, expect convergence and/or collect positive funding
    else if (basisPercentage < -0.5) { // If perp is 0.5% or more below spot
         // Simplified: assume prices converge to spot after a period.
        const potentialFundingPay = fundingPerPeriod * zetaMarkPrice; // per unit of SOL longed
        const estimatedProfit = -basis - (2 * MODEL_FEES_PERCENTAGE * spotPrice) - potentialFundingPay; // Gross profit minus two legs of fees and paid funding

        if (estimatedProfit > 0.1) { // Example threshold for meaningful profit
            opportunityDescription = `**LATENT OPPORTUNITY (Short Spot / Long Perp):** Zeta Perp is ${(-basisPercentage).toFixed(2)}% below Spot.`;
            opportunityDescription += `<br>Projected gain from convergence & funding: ~${estimatedProfit.toFixed(4)} USDC per SOL (before slippage).`;
            opportunityDescription += `<br>Action: Short Spot SOL, Long SOL-PERP on Zeta. (Funding rate: ${(fundingPerPeriod * 100).toFixed(4)}% per ${FUNDING_RATE_PERIOD_HOURS}h)`;
            opportunityResultDiv.className = 'opportunity positive';
        }
    }

    // Consider explicit funding rate arb if basis is neutral but funding is extreme
    else if (Math.abs(zetaFundingRateAnnualized) > 0.05) { // If annualized funding is > 5%
        const potentialFunding = fundingPerPeriod * zetaMarkPrice;
        if (potentialFunding > 0.05) { // Significant potential to collect
             opportunityDescription = `**LATENT OPPORTUNITY (Funding Rate Arb):** High positive funding rate (${(zetaFundingRateAnnualized * 100).toFixed(2)}% annualized) on Zeta.`;
             opportunityDescription += `<br>Action: Long Spot SOL, Short SOL-PERP on Zeta to collect funding.`;
             opportunityResultDiv.className = 'opportunity positive';
        } else if (potentialFunding < -0.05) { // Significant potential to pay
             opportunityDescription = `**LATENT OPPORTUNITY (Funding Rate Arb):** High negative funding rate (${(zetaFundingRateAnnualized * 100).toFixed(2)}% annualized) on Zeta.`;
             opportunityDescription += `<br>Action: Short Spot SOL, Long SOL-PERP on Zeta to collect funding.`;
             opportunityResultDiv.className = 'opportunity positive';
        }
    }


    opportunityResultDiv.innerHTML = opportunityDescription;
}

// --- Manual Trade Initiation (Latency-Agnostic) ---
async function initiateManualTrade() {
    if (!userPublicKey) {
        tradeStatusDiv.className = 'status-message error';
        tradeStatusDiv.textContent = 'Please connect your wallet first.';
        return;
    }

    tradeStatusDiv.className = 'status-message';
    tradeStatusDiv.textContent = 'Preparing manual arbitrage transaction...';

    // This is where your detailed manual trade logic would go.
    // Given the "latency agnostic" nature, you're not trying to execute
    // in sub-millisecond speeds. You'd build and sign transactions
    // for both the spot and perp legs of the arbitrage.
    // This would involve:
    // 1. Determining the desired size for the trade (e.g., 1 SOL).
    // 2. Using Jupiter Aggregator SDK/API to find the best route for SPOT swap (e.g., SOL to USDC or vice versa).
    // 3. Using Zeta Markets SDK to create the PERP position (long or short).
    // 4. Potentially building a transaction *bundle* if your RPC provider supports it (like Jito)
    //    to increase the chances of both legs executing close together.
    // 5. Signing these transactions with `window.solana.signAllTransactions` or `signTransaction`.
    // 6. Sending them to the Solana network.

    // --- SIMULATED TRADE ---
    await new Promise(resolve => setTimeout(resolve, 3000)); // Simulate transaction building and network delay

    const opportunity = opportunityResultDiv.innerHTML; // Check what opportunity was identified
    let simulatedTxnSuccessful = Math.random() > 0.2; // 80% chance of success for simulation

    if (simulatedTxnSuccessful) {
        tradeStatusDiv.className = 'status-message success';
        tradeStatusDiv.innerHTML = `Manual arbitrage initiated successfully! Check your wallet. <br> (Simulated for: ${opportunity.split('<br>')[0]})`;
    } else {
        tradeStatusDiv.className = 'status-message error';
        tradeStatusDiv.innerHTML = `Manual arbitrage failed! Review your wallet balance and network status. <br> (Simulated for: ${opportunity.split('<br>')[0]})`;
    }
}


// --- Event Listeners ---
connectWalletBtn.addEventListener('click', connectWallet);
refreshDataBtn.addEventListener('click', fetchDataAndModel);
initiateTradeBtn.addEventListener('click', initiateManualTrade);

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    // Check if wallet is already connected on page load (Phantom often remembers)
    if (window.solana && window.solana.isConnected && window.solana.publicKey) {
        userPublicKey = new PublicKey(window.solana.publicKey.toString());
        walletStatusDiv.textContent = `${userPublicKey.toBase58().substring(0, 6)}... Connected`;
        initiateTradeBtn.disabled = false;
        fetchDataAndModel();
    } else {
        walletStatusDiv.textContent = 'Disconnected';
        generalStatusDiv.textContent = 'Connect your wallet to begin.';
    }
});