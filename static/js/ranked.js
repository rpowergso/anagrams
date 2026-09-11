const defaultRanked = {elo:1000, played:0, solved:0, streak:0, bestStreak:0, totalTime:0};
let rankedProfile = {...defaultRanked, ...JSON.parse(localStorage.getItem('rankedProfile') || '{}')};
let rankedPuzzle = null;
let rankedSubmitting = false;
const byId = id => document.getElementById(id);

function saveRanked(){localStorage.setItem('rankedProfile',JSON.stringify(rankedProfile));renderRankedHeader()}
function renderRankedHeader(){
  byId('rankedElo').textContent=rankedProfile.elo;
  const accuracy=rankedProfile.played?Math.round(rankedProfile.solved/rankedProfile.played*100):0;
  byId('rankedStats').textContent=`Solved ${rankedProfile.solved}/${rankedProfile.played} • ${accuracy}% accuracy • Streak ${rankedProfile.streak} • Best ${rankedProfile.bestStreak}`;
}
function tileWord(word,className=''){
  const box=document.createElement('div');box.className=`ranked-word ${className}`;
  [...word].forEach(char=>{const tile=document.createElement('span');tile.className='tile small';tile.textContent=char;box.appendChild(tile)});return box;
}
function showRankedAnswers(answers=[],foundWord=''){
  const container=byId('rankedAnswers');container.innerHTML='';
  answers.forEach(answer=>{const item=document.createElement('div');item.className=`ranked-answer ${answer.word===foundWord?'found':''}`;item.textContent=answer.source==='POOL'?`FROM WORD POOL → ${answer.word}`:`${answer.source} → ${answer.word}`;container.appendChild(item)});
}
async function loadRankedPuzzle(){
  rankedPuzzle=null;rankedSubmitting=false;
  byId('rankedNext').hidden=true;byId('rankedForm').hidden=false;byId('rankedResult').textContent='';byId('rankedAnswers').innerHTML='';byId('rankedStatus').textContent='Building a verified board…';
  const response=await fetch('/ranked-puzzle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({elo:rankedProfile.elo})});
  const data=await response.json();if(!response.ok){byId('rankedStatus').textContent=data.error;return}rankedPuzzle=data;
  byId('puzzleRating').textContent=data.rating;
  byId('legalCount').textContent=`${data.legalMoveCount} LEGAL PLAY${data.legalMoveCount===1?'':'S'}`;
  byId('rankedStatus').textContent='Find the strongest play on the board';
  byId('rankedBoard').innerHTML='';data.boardWords.forEach(word=>{const block=tileWord(word,'word-block');byId('rankedBoard').appendChild(block)});
  byId('rankedPool').innerHTML='';data.pool.forEach((letter,index)=>{const tile=document.createElement('span');tile.className=`tile pool-tile ${index===data.pool.length-1?'flipped':''}`;tile.textContent=letter;byId('rankedPool').appendChild(tile)});
  byId('rankedInput').value='';byId('rankedInput').focus();
}
function finishRanked(data,solved){
  rankedProfile.elo=data.newElo;rankedProfile.played++;rankedProfile.streak=solved?rankedProfile.streak+1:0;
  if(solved){rankedProfile.solved++;rankedProfile.totalTime+=data.elapsed;rankedProfile.bestStreak=Math.max(rankedProfile.bestStreak,rankedProfile.streak)}saveRanked();
  byId('rankedForm').hidden=true;byId('rankedNext').hidden=false;rankedPuzzle=null;rankedSubmitting=false;
}
byId('rankedForm').addEventListener('submit',async event=>{event.preventDefault();if(!rankedPuzzle||rankedSubmitting)return;const word=byId('rankedInput').value.trim().toUpperCase();
  rankedSubmitting=true;
  try {
    const response=await fetch('/ranked-submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:rankedPuzzle.id,word,elo:rankedProfile.elo})});const data=await response.json();
    if(!response.ok){byId('rankedResult').textContent=data.error||'Could not submit that word. Load the next puzzle.';byId('rankedForm').hidden=true;byId('rankedNext').hidden=false;rankedPuzzle=null;return}
    if(data.correct){const play=data.source==='POOL'?`FROM WORD POOL → ${data.word}`:`${data.source} → ${data.word}`;byId('rankedResult').textContent=`${play} • ${data.elapsed}s • +${data.delta} Elo`;showRankedAnswers(data.answers,data.word);finishRanked(data,true)}else{if(typeof data.newElo==='number'){rankedProfile.elo=data.newElo;saveRanked()}byId('rankedInput').value='';if(data.failed){byId('rankedResult').textContent=`${data.message} ${data.delta} Elo • All legal plays`;showRankedAnswers(data.answers);finishRanked(data,false)}else{byId('rankedResult').textContent=`${data.message||'That is not a legal play.'}${data.delta?` ${data.delta} Elo`:''} • ${data.strikesLeft} strike${data.strikesLeft===1?'':'s'} left`;byId('rankedInput').focus()}}
  } catch(error) {
    byId('rankedResult').textContent='Could not submit that word. Please try again.';
  } finally {
    rankedSubmitting=false;
  }
});
byId('rankedGiveUp').addEventListener('click',async()=>{if(!rankedPuzzle||rankedSubmitting)return;rankedSubmitting=true;const response=await fetch('/ranked-give-up',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:rankedPuzzle.id,elo:rankedProfile.elo})});const data=await response.json();if(!response.ok){byId('rankedResult').textContent=data.error||'Could not give up this puzzle.';rankedSubmitting=false;return}
  byId('rankedResult').textContent=`${data.delta} Elo • All legal plays`;showRankedAnswers(data.answers);finishRanked(data,false)
});
byId('rankedNext').addEventListener('click',loadRankedPuzzle);renderRankedHeader();loadRankedPuzzle();
document.addEventListener('keydown',event=>{
  if(event.key==='Enter'&&!byId('rankedNext').hidden){event.preventDefault();loadRankedPuzzle()}
});
